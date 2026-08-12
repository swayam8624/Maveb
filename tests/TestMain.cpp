#include <aether/core/Diagnostics.hpp>
#include <aether/core/Error.hpp>
#include <aether/core/JobSystem.hpp>
#include <aether/core/Log.hpp>
#include <aether/core/Profiler.hpp>
#include <aether/core/ResourceLocator.hpp>
#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/hybrid/ProxyMeshCodec.hpp>
#include <aether/hybrid/ProxyPlyLoader.hpp>
#include <aether/mesh/Animation.hpp>
#include <aether/mesh/GltfExporter.hpp>
#include <aether/mesh/GltfLoader.hpp>
#include <aether/mesh/PlyExporter.hpp>
#include <aether/mesh/TransparentSort.hpp>
#include <aether/package/Package.hpp>
#include <aether/package/Sha256.hpp>
#include <aether/reconstruction/DenseTsdfVolume.hpp>
#include <aether/reconstruction/GeometryEvaluation.hpp>
#include <aether/reconstruction/RecordedProviders.hpp>
#include <aether/reconstruction/SparseModelValidator.hpp>
#include <aether/rendergraph/RenderGraph.hpp>
#include <aether/scene/Camera.hpp>
#include <aether/scene/CameraController.hpp>
#include <aether/scene/CameraPath.hpp>
#include <aether/scene/ImageBasedLighting.hpp>
#include <aether/scene/Lighting.hpp>
#include <aether/scene/Scene.hpp>
#include <aether/scene/Shadows.hpp>

#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <span>
#include <string>
#include <thread>
#include <vector>

namespace {

int failures = 0;

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testErrors() {
    const aether::Error error{aether::ErrorCode::io, "read failed", "scene.aether"};
    expect(error.describe() == "read failed [scene.aether]", "Error context is preserved");
}

void testResourceLocator() {
    const auto root = std::filesystem::temp_directory_path() / "aether-resource-test";
    std::filesystem::create_directories(root);
    const auto file = root / "shader.metallib";
    {
        std::ofstream stream(file);
        stream << "fixture";
    }

    aether::ResourceLocator locator;
    locator.addRoot(root);
    const auto found = locator.find("shader.metallib");
    expect(found.has_value(), "Resource locator finds a file below an allowed root");
    expect(!locator.find("../secret").has_value(), "Resource locator rejects traversal");
    std::filesystem::remove_all(root);
}

void testDiagnostics() {
    const auto path = std::filesystem::temp_directory_path() / "aether-diagnostics-test.json";
    aether::Log::instance().write(aether::LogLevel::warning, "fixture log");
    const aether::DiagnosticsContext context{"0.test", {{"gpu", "fixture"}}};
    const auto result = aether::Diagnostics::writeReport(path, context);
    expect(result.has_value(), "Diagnostics report is written atomically");
    std::ifstream stream(path);
    const std::string contents((std::istreambuf_iterator<char>(stream)),
                               std::istreambuf_iterator<char>());
    expect(contents.find("\"applicationVersion\": \"0.test\"") != std::string::npos,
           "Diagnostics report includes application version");
    expect(contents.find("fixture log") != std::string::npos,
           "Diagnostics report includes retained logs");
    expect(contents.find("Serial") == std::string::npos,
           "Diagnostics report excludes machine serial identifiers");
    std::filesystem::remove(path);
}

void testSparseCoverageValidation() {
    const auto root = std::filesystem::temp_directory_path() / "aether-sparse-coverage-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    {
        std::ofstream images(root / "images.txt");
        images << "1 0.9987502604 0 0.0499791693 0 1 0 0 1 a.jpg\n\n"
                  "2 1 0 0 0 0 0 0 1 b.jpg\n\n"
                  "3 0.9987502604 0 -0.0499791693 0 -1 0 0 1 c.jpg\n\n";
        std::ofstream points(root / "points3D.txt");
        points << "1 0 0 3 128 128 128 0.1 1 0 2 0 3 0\n";
    }
    aether::reconstruction::SparseCoverageThresholds thresholds;
    thresholds.minimumTrackedPoints = 1;
    auto valid = aether::reconstruction::validateSparseTextModel(root, 3, thresholds);
    expect(valid.has_value() && valid->passed(),
           "Connected COLMAP poses with baseline and tracks pass coverage validation");
    if (valid) {
        expect(valid->registeredImages == 3 && valid->connectedImages == 3,
               "Sparse coverage report retains registration and graph evidence");
        expect(valid->maximumViewAngleDegrees > 10.0,
               "Sparse coverage report measures camera angular diversity");
    }
    thresholds.minimumTrackedPoints = 2;
    auto weak = aether::reconstruction::validateSparseTextModel(root, 3, thresholds);
    expect(weak.has_value() && !weak->passed() && !weak->issues.empty(),
           "A structurally valid but weak sparse model returns actionable coverage issues");
    {
        std::ofstream points(root / "points3D.txt", std::ios::trunc);
        points << "1 0 0 3 128 128 128 0.1 99 0\n";
    }
    expect(!aether::reconstruction::validateSparseTextModel(root, 3, thresholds).has_value(),
           "Sparse point tracks referencing unknown images are rejected as corrupt data");
    {
        std::ofstream images(root / "images.txt", std::ios::trunc);
        images << "1 1 0 0 0 0 0 0 1 a.jpg\n0 0\n";
    }
    expect(!aether::reconstruction::validateSparseTextModel(root, 3, thresholds).has_value(),
           "Incomplete COLMAP observation triples are rejected as corrupt data");
    std::filesystem::remove_all(root);
}

void testOracleTsdfReconstruction() {
    aether::reconstruction::DenseTsdfConfig config;
    config.dimensions = {21, 21, 17};
    config.originMetres = {-0.4, -0.4, 0.68};
    config.voxelSizeMetres = 0.04;
    config.truncationDistanceMetres = 0.08;
    config.minimumDepthMetres = 0.1;
    config.maximumDepthMetres = 2.0;
    auto volume = aether::reconstruction::DenseTsdfVolume::create(config);
    expect(volume.has_value(), "Valid bounded dense TSDF volume is created");
    if (!volume)
        return;
    expect(!volume->extractMesh().has_value(), "An unobserved TSDF volume cannot produce geometry");

    constexpr std::uint32_t width = 64;
    constexpr std::uint32_t height = 64;
    std::vector<std::byte> color(static_cast<std::size_t>(width) * height * 3, std::byte{128});
    std::vector<std::byte> depth(static_cast<std::size_t>(width) * height * sizeof(float));
    constexpr float planeDepth = 1.0F;
    for (std::size_t index = 0; index < static_cast<std::size_t>(width) * height; ++index)
        std::memcpy(depth.data() + index * sizeof(float), &planeDepth, sizeof(float));

    aether::capture::CapturePacket packet;
    packet.frameId = 1;
    packet.sourceId = "oracle-plane";
    packet.sourceKind = aether::capture::CaptureSourceKind::recordedRgbd;
    packet.calibration.id = packet.sourceId;
    packet.calibration.width = width;
    packet.calibration.height = height;
    packet.calibration.fx = 60.0;
    packet.calibration.fy = 60.0;
    packet.calibration.cx = 31.5;
    packet.calibration.cy = 31.5;
    packet.colorPlanes.push_back(aether::capture::ImagePlane{
        aether::capture::makeOwnedBuffer(std::move(color)),
        aether::capture::PixelFormat::rgb8,
        width,
        height,
        width * 3,
    });
    packet.depthMetres = aether::capture::ImagePlane{
        aether::capture::makeOwnedBuffer(std::move(depth)),
        aether::capture::PixelFormat::depthFloat32Metres,
        width,
        height,
        width * static_cast<std::uint32_t>(sizeof(float)),
    };
    packet.cameraToWorld = aether::capture::RigidPose{};

    aether::reconstruction::RecordedPoseProvider poseProvider;
    aether::reconstruction::RecordedRgbdDepthProvider depthProvider;
    auto pose = poseProvider.estimate(packet);
    auto observation = pose ? depthProvider.estimate(packet, *pose)
                            : aether::Result<aether::reconstruction::DepthObservation>(
                                  std::unexpected(pose.error()));
    expect(pose.has_value() && observation.has_value(),
           "Known recorded pose and metric depth providers accept oracle data");
    if (!pose || !observation)
        return;
    auto boundsEstimator = aether::reconstruction::DenseTsdfBoundsEstimator::create({
        .pixelStride = 4,
        .maximumAxisVoxels = 64,
        .minimumVoxelSizeMetres = 0.01,
        .paddingMetres = 0.08,
    });
    expect(boundsEstimator.has_value() &&
               boundsEstimator->observe(packet, *pose, *observation).has_value(),
           "Calibrated metric depth contributes to automatic TSDF bounds");
    auto estimatedBounds = boundsEstimator
                               ? boundsEstimator->estimate()
                               : aether::Result<aether::reconstruction::DenseTsdfBoundsResult>(
                                     std::unexpected(boundsEstimator.error()));
    expect(estimatedBounds.has_value() && estimatedBounds->sampledPoints == 256 &&
               estimatedBounds->volume.dimensions[2] >= 2 &&
               estimatedBounds->volume.dimensions[0] <= 64 &&
               estimatedBounds->volume.originMetres[2] < planeDepth,
           "Automatic TSDF bounds enclose observed surfaces within their voxel budget");
    expect(volume->integrate(packet, *pose, *observation).has_value(),
           "Known-pose metric depth updates the TSDF");
    auto mesh = volume->extractMesh();
    expect(mesh.has_value() && !mesh->primitives.empty() && !mesh->primitives[0].indices.empty(),
           "Observed TSDF extracts a connected zero-crossing surface");
    if (!mesh)
        return;

    std::vector<std::array<double, 3>> reference;
    for (int y = -10; y <= 10; ++y)
        for (int x = -10; x <= 10; ++x)
            reference.push_back(
                {static_cast<double>(x) * 0.04, static_cast<double>(y) * 0.04, 1.0});
    auto metrics = aether::reconstruction::evaluateGeometry(*mesh, reference, 0.05);
    expect(metrics.has_value() && metrics->accuracyMeanMetres <= 0.02,
           "Oracle plane reconstruction stays within half a voxel accuracy");
    expect(metrics.has_value() && metrics->invalidIndices == 0 && metrics->degenerateTriangles == 0,
           "Extracted oracle mesh contains valid non-degenerate triangles");

    const auto firstPath = std::filesystem::temp_directory_path() / "aether-oracle-first.ply";
    const auto secondPath = std::filesystem::temp_directory_path() / "aether-oracle-second.ply";
    expect(aether::mesh::exportToPly(*mesh, firstPath).has_value() &&
               aether::mesh::exportToPly(*mesh, secondPath).has_value(),
           "Hardened PLY exporter atomically writes oracle geometry");
    std::ifstream first(firstPath, std::ios::binary);
    std::ifstream second(secondPath, std::ios::binary);
    const std::string firstBytes((std::istreambuf_iterator<char>(first)),
                                 std::istreambuf_iterator<char>());
    const std::string secondBytes((std::istreambuf_iterator<char>(second)),
                                  std::istreambuf_iterator<char>());
    expect(firstBytes == secondBytes, "Identical oracle meshes produce deterministic PLY bytes");
    std::filesystem::remove(firstPath);
    std::filesystem::remove(secondPath);
}

void testProxyMeshContract() {
    const auto root = std::filesystem::temp_directory_path() / "aether-proxy-mesh-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto asciiPath = root / "proxy-ascii.ply";
    {
        std::ofstream stream(asciiPath);
        stream << "ply\nformat ascii 1.0\n"
                  "element vertex 3\n"
                  "property float x\nproperty float y\nproperty float z\n"
                  "property float nx\nproperty float ny\nproperty float nz\n"
                  "property uchar red\nproperty uchar green\nproperty uchar blue\n"
                  "element face 1\nproperty list uchar uint vertex_indices\nend_header\n"
                  "0 0 0 0 0 2 255 0 0\n"
                  "1 0 0 0 0 2 0 255 0\n"
                  "0 1 0 0 0 2 0 0 255\n"
                  "3 0 1 2\n";
    }
    auto ascii = aether::hybrid::ProxyPlyLoader::load(asciiPath);
    expect(ascii.has_value() && ascii->vertices.size() == 3 && ascii->indices.size() == 3,
           "ASCII triangle proxy PLY loads into bounded canonical geometry");
    if (ascii) {
        expect(std::abs(ascii->vertices[0].normal[2] - 1.0F) < 1.0e-6F,
               "Proxy PLY normals are normalized during import");
        auto encoded = aether::hybrid::ProxyMeshCodec::encode(*ascii);
        auto decoded =
            encoded ? aether::hybrid::ProxyMeshCodec::decode(*encoded)
                    : aether::Result<aether::hybrid::ProxyMesh>(std::unexpected(encoded.error()));
        expect(decoded.has_value() && decoded->indices == ascii->indices &&
                   decoded->vertices[0].colorRgba == ascii->vertices[0].colorRgba,
               "Canonical proxy chunk round-trips without ABI-dependent layouts");
        if (encoded) {
            (*encoded)[0] = std::byte{0};
            expect(!aether::hybrid::ProxyMeshCodec::decode(*encoded).has_value(),
                   "Canonical proxy decoder rejects invalid magic");
        }
    }
    const auto binaryPath = root / "proxy-binary.ply";
    {
        std::ofstream stream(binaryPath, std::ios::binary);
        stream << "ply\nformat binary_little_endian 1.0\n"
                  "comment Open3D fixture\n"
                  "element vertex 3\n"
                  "property double x\nproperty double y\nproperty double z\n"
                  "property double nx\nproperty double ny\nproperty double nz\n"
                  "property uchar red\nproperty uchar green\nproperty uchar blue\n"
                  "element face 1\nproperty list uchar uint vertex_indices\nend_header\n";
        const std::array<std::array<double, 6>, 3> vertices{
            {{{0, 0, 0, 0, 0, 1}}, {{1, 0, 0, 0, 0, 1}}, {{0, 1, 0, 0, 0, 1}}}};
        for (const auto& vertex : vertices) {
            for (const double value : vertex)
                stream.write(reinterpret_cast<const char*>(&value), sizeof(value));
            constexpr std::array<std::uint8_t, 3> color{128, 192, 255};
            stream.write(reinterpret_cast<const char*>(color.data()), color.size());
        }
        constexpr std::uint8_t count = 3;
        constexpr std::array<std::uint32_t, 3> indices{0, 1, 2};
        stream.write(reinterpret_cast<const char*>(&count), sizeof(count));
        stream.write(reinterpret_cast<const char*>(indices.data()),
                     static_cast<std::streamsize>(indices.size() * sizeof(indices[0])));
    }
    auto binary = aether::hybrid::ProxyPlyLoader::load(binaryPath);
    expect(binary.has_value() && binary->vertices.size() == 3 && binary->indices[2] == 2,
           "Open3D-style binary little-endian proxy PLY loads strictly");
    {
        std::ofstream stream(asciiPath, std::ios::app);
        stream << "trailing";
    }
    expect(!aether::hybrid::ProxyPlyLoader::load(asciiPath).has_value(),
           "Proxy PLY importer rejects trailing payload data");
    std::filesystem::remove_all(root);
}

void testProfiler() {
    aether::Profiler::instance().record("test", 1.25);
    const auto events = aether::Profiler::instance().snapshotAndReset();
    expect(events.size() == 1, "Profiler returns recorded events");
    expect(aether::Profiler::instance().snapshotAndReset().empty(),
           "Profiler snapshot resets data");
}

void testJobSystem() {
    aether::JobSystem jobs(2);
    auto successful =
        jobs.submit("successful", [](aether::JobContext& context) -> aether::Result<void> {
            context.setProgress(0.5);
            return {};
        });
    successful.wait();
    expect(successful.status() == aether::JobStatus::succeeded, "Job completes successfully");
    expect(successful.progress() == 1.0, "Successful job reports complete progress");

    auto failed = jobs.submit("failed", [](aether::JobContext&) -> aether::Result<void> {
        return aether::fail(aether::ErrorCode::io, "fixture failure");
    });
    failed.wait();
    expect(failed.status() == aether::JobStatus::failed, "Job failure is preserved");
    expect(failed.error().has_value(), "Failed job exposes its structured error");

    auto cancellable =
        jobs.submit("cancellable", [](aether::JobContext& context) -> aether::Result<void> {
            while (!context.isCancellationRequested()) {
                std::this_thread::yield();
            }
            return aether::fail(aether::ErrorCode::cancelled, "cancelled by test");
        });
    cancellable.cancel();
    cancellable.wait();
    expect(cancellable.status() == aether::JobStatus::cancelled, "Cooperative cancellation works");
}

void testRenderGraph() {
    using aether::rendergraph::RenderGraph;
    RenderGraph graph;
    const auto source = graph.createResource("Source", false);
    const auto projected = graph.createResource("Projected");
    const auto output = graph.createResource("Output", false);
    const auto unused = graph.createResource("Unused");
    std::vector<std::string> execution;

    expect(
        graph.addPass("Project", {source}, {projected}, [&] { execution.emplace_back("Project"); })
            .has_value(),
        "Project pass is accepted");
    expect(graph
               .addPass("Composite", {projected}, {output},
                        [&] { execution.emplace_back("Composite"); })
               .has_value(),
           "Composite pass is accepted");
    expect(graph.addPass("Unused", {}, {unused}, [&] { execution.emplace_back("Unused"); })
               .has_value(),
           "Unused pass is accepted");
    expect(graph.markOutput(output).has_value(), "Output resource is exported");

    auto compiled = graph.compile();
    expect(compiled.has_value(), "Render graph compiles");
    if (compiled) {
        expect(compiled->passes().size() == 2, "Dead render pass is culled");
        compiled->execute();
        expect(execution == std::vector<std::string>({"Project", "Composite"}),
               "Dependencies execute in order");
        expect(compiled->lifetimes().size() == 3, "Resource lifetimes include live resources");
        expect(compiled->dot().find("Unused") == std::string::npos,
               "Graph visualization excludes culled work");
    }
}

void testSceneTransforms() {
    aether::scene::Scene scene;
    const auto parent = scene.createEntity("Parent");
    const auto child = scene.createEntity("Child");
    aether::scene::Transform parentTransform;
    parentTransform.translation = {2.0F, 0.0F, 0.0F};
    aether::scene::Transform childTransform;
    childTransform.translation = {0.0F, 3.0F, 0.0F};
    expect(scene.setLocalTransform(parent, parentTransform).has_value(),
           "Parent transform is accepted");
    expect(scene.setLocalTransform(child, childTransform).has_value(),
           "Child transform is accepted");
    expect(scene.setParent(child, parent).has_value(), "Scene entity can be parented");
    auto world = scene.worldMatrix(child);
    expect(world.has_value(), "Child world matrix is evaluated");
    if (world) {
        const simd_float4 origin = simd_mul(*world, simd_float4{0.0F, 0.0F, 0.0F, 1.0F});
        expect(std::abs(origin.x - 2.0F) < 1.0e-5F && std::abs(origin.y - 3.0F) < 1.0e-5F,
               "Parent and child transforms compose in column-vector order");
    }
    expect(!scene.setParent(parent, child).has_value(), "Scene hierarchy cycles are rejected");
    expect(scene.destroyEntity(parent).has_value(), "Entity destruction succeeds");
    expect(!scene.valid(parent), "Stale entity generation is invalidated");
    expect(scene.worldMatrix(child).has_value(), "Destroying a parent safely orphans its child");

    aether::scene::Transform mirrored;
    mirrored.translation = {1.0F, -2.0F, 3.0F};
    mirrored.rotation = simd_quaternion(0.7F, simd_normalize(simd_float3{1.0F, 2.0F, 3.0F}));
    mirrored.scale = {-2.0F, 3.0F, 0.5F};
    const auto decomposed = aether::scene::decomposeTransform(mirrored.matrix());
    expect(decomposed.has_value(), "Mirrored affine transform decomposes into editor TRS");
    if (decomposed) {
        const auto rebuilt = decomposed->matrix();
        float maximumDifference = 0.0F;
        for (std::size_t column = 0; column < 4; ++column)
            for (std::size_t row = 0; row < 4; ++row)
                maximumDifference =
                    std::max(maximumDifference, std::abs(rebuilt.columns[column][row] -
                                                         mirrored.matrix().columns[column][row]));
        expect(maximumDifference < 1.0e-4F,
               "Decomposed mirrored transform round-trips without matrix drift");
    }
    auto sheared = matrix_identity_float4x4;
    sheared.columns[1].x = 0.25F;
    expect(!aether::scene::decomposeTransform(sheared).has_value(),
           "Editor TRS decomposition rejects shear instead of corrupting it");
}

void testCameraProjection() {
    aether::scene::Camera camera;
    camera.infiniteFarPlane = false;
    camera.nearPlane = 0.1F;
    camera.farPlane = 100.0F;
    auto projection = camera.projectionMatrix(16.0F / 9.0F);
    expect(projection.has_value(), "Valid reverse-Z perspective matrix is created");
    if (projection) {
        const simd_float4 nearClip =
            simd_mul(*projection, simd_float4{0.0F, 0.0F, -camera.nearPlane, 1.0F});
        const simd_float4 farClip =
            simd_mul(*projection, simd_float4{0.0F, 0.0F, -camera.farPlane, 1.0F});
        expect(std::abs((nearClip.z / nearClip.w) - 1.0F) < 1.0e-5F,
               "Reverse-Z maps the near plane to one");
        expect(std::abs(farClip.z / farClip.w) < 1.0e-5F, "Reverse-Z maps the far plane to zero");
    }
    expect(!camera.projectionMatrix(0.0F).has_value(), "Invalid camera aspect is rejected");
}

void testCameraController() {
    aether::scene::CameraController controller;
    const float initialZ = controller.position().z;
    controller.setMoving(aether::scene::CameraMove::forward, true);
    controller.update(0.1);
    expect(controller.position().z < initialZ, "Fly camera moves forward in right-handed view");
    controller.clearMovement();
    const simd_float3 stopped = controller.position();
    controller.update(0.1);
    expect(simd_length(controller.position() - stopped) < 1.0e-6F,
           "Cleared camera input does not continue moving");
    controller.addLookDelta(0.0F, 100000.0F);
    expect(std::abs(controller.pitch()) < 1.56F, "Fly camera pitch is clamped below singularity");
}

void testCameraPath() {
    aether::scene::CameraPath path;
    aether::scene::CameraKeyframe first;
    first.seconds = 0.0;
    first.transform.translation = {0.0F, 0.0F, 0.0F};
    first.exposureEv = -1.0F;
    aether::scene::CameraKeyframe second;
    second.seconds = 2.0;
    second.transform.translation = {2.0F, 4.0F, 6.0F};
    second.transform.rotation = simd_quaternion(1.0F, simd_float3{0.0F, 1.0F, 0.0F});
    second.verticalFieldOfViewRadians = 0.8F;
    second.exposureEv = 1.0F;
    path.editableKeyframes() = {first, second};
    expect(path.validate().has_value(), "Camera path accepts finite ordered keyframes");
    auto midpoint = path.sample(1.0);
    expect(midpoint.has_value() &&
               simd_length(midpoint->transform.translation - simd_float3{1.0F, 2.0F, 3.0F}) <
                   1.0e-6F &&
               std::abs(midpoint->exposureEv) < 1.0e-6F,
           "Camera path interpolates position and exposure at timeline midpoint");

    const auto file = std::filesystem::temp_directory_path() / "aether-camera-path.json";
    std::filesystem::remove(file);
    expect(path.save(file).has_value(), "Camera path saves atomically as versioned JSON");
    auto loaded = aether::scene::CameraPath::load(file);
    expect(loaded.has_value() && loaded->keyframes().size() == 2 &&
               std::abs(loaded->duration() - 2.0) < 1.0e-9,
           "Camera path JSON round-trips with duration");
    std::filesystem::remove(file);

    second.seconds = 0.0;
    path.editableKeyframes() = {first, second};
    expect(!path.validate().has_value(), "Camera path rejects duplicate timestamps");
}

void testGltfLoader() {
    const auto path = std::filesystem::path(AETHER_TEST_FIXTURES) / "triangle.gltf";
    auto loaded = aether::mesh::GltfLoader::load(path);
    expect(loaded.has_value(), "Valid glTF fixture loads");
    if (loaded) {
        expect(loaded->primitives.size() == 1, "glTF primitive is retained");
        expect(loaded->instances.size() == 1, "glTF scene node creates one mesh instance");
        expect(loaded->vertexCount() == 3 && loaded->indexCount() == 3,
               "glTF vertex and index counts match");
        expect(loaded->materials.size() == 2, "Default and authored materials are present");
        expect(std::abs(loaded->materials[1].metallic - 0.25F) < 1.0e-6F,
               "Metallic-roughness material factors load");
        expect(simd_length(loaded->primitives[0].vertices[0].normal) > 0.99F,
               "Missing normals are generated");
    }
    aether::mesh::GltfLimits tinyLimits;
    tinyLimits.maximumFileBytes = 1;
    expect(!aether::mesh::GltfLoader::load(path, tinyLimits).has_value(),
           "glTF file-size limit is enforced");

    const auto instancedPath =
        std::filesystem::path(AETHER_TEST_FIXTURES) / "instanced-triangle.gltf";
    auto instanced = aether::mesh::GltfLoader::load(instancedPath);
    expect(instanced.has_value(), "Instanced and nested glTF scene loads");
    if (instanced) {
        expect(instanced->primitives.size() == 1 && instanced->instances.size() == 3,
               "glTF instances share one geometry primitive");
        const auto firstOrigin =
            simd_mul(instanced->instances[0].worldTransform, simd_float4{0.0F, 0.0F, 0.0F, 1.0F});
        const auto secondOrigin =
            simd_mul(instanced->instances[1].worldTransform, simd_float4{0.0F, 0.0F, 0.0F, 1.0F});
        expect(std::abs(firstOrigin.x - 2.0F) < 1.0e-6F &&
                   std::abs(secondOrigin.x + 1.0F) < 1.0e-6F &&
                   std::abs(secondOrigin.y - 3.0F) < 1.0e-6F,
               "Nested glTF world transforms are composed in scene order");
    }
    aether::mesh::GltfLimits instanceLimit;
    instanceLimit.maximumInstances = 1;
    expect(!aether::mesh::GltfLoader::load(instancedPath, instanceLimit).has_value(),
           "glTF scene instance limit is enforced");

    const std::array<std::size_t, 3> candidates{0, 1, 2};
    const std::array<simd_float3, 3> centers{simd_float3{0.0F, 0.0F, -2.0F},
                                             simd_float3{0.0F, 0.0F, -5.0F},
                                             simd_float3{0.0F, 0.0F, 2.0F}};
    const auto transparentOrder =
        aether::mesh::stableBackToFront(candidates, centers, simd_float3{0.0F, 0.0F, 0.0F});
    expect(transparentOrder == std::vector<std::size_t>({1, 0, 2}),
           "Transparent instances sort far-to-near with stable equal-distance ties");

    const auto animatedPath =
        std::filesystem::path(AETHER_TEST_FIXTURES) / "animated-triangle.gltf";
    auto animated = aether::mesh::GltfLoader::load(animatedPath);
    expect(animated.has_value(), "glTF animation accessors and channels load");
    if (animated) {
        expect(animated->animations.size() == 1 && animated->animations[0].channels.size() == 1 &&
                   std::abs(animated->animations[0].durationSeconds - 1.0F) < 1.0e-6F,
               "glTF animation clip retains channel and duration");
        const auto pose = aether::mesh::sampleAnimation(*animated, 0, 0.5F, false);
        expect(pose.has_value() && std::abs((*pose)[0].translation.x - 2.0F) < 1.0e-6F,
               "Loaded glTF animation evaluates at runtime");
    }
    const auto skinnedPath = std::filesystem::path(AETHER_TEST_FIXTURES) / "skinned-triangle.gltf";
    auto skinned = aether::mesh::GltfLoader::load(skinnedPath);
    expect(skinned.has_value(), "glTF skin, joints, weights, and inverse binds load");
    if (skinned) {
        expect(skinned->skins.size() == 1 && skinned->skins[0].jointNodeIndices.size() == 1 &&
                   skinned->instances[0].skinIndex == 0 && skinned->primitives[0].hasSkinAttributes,
               "glTF skin remains associated with its mesh-node instance");
        expect(skinned->primitives[0].vertices[0].joints.x == 0 &&
                   std::abs(skinned->primitives[0].vertices[0].weights.x - 1.0F) < 1.0e-6F,
               "glTF joint indices and normalized weights reach the mesh vertex ABI");
    }
    const auto morphedPath = std::filesystem::path(AETHER_TEST_FIXTURES) / "morphed-triangle.gltf";
    auto morphed = aether::mesh::GltfLoader::load(morphedPath);
    expect(morphed.has_value(), "glTF morph targets and node weights load");
    if (!morphed)
        std::cerr << morphed.error().describe() << '\n';
    if (morphed) {
        expect(morphed->primitives[0].morphTargets.size() == 1 &&
                   std::abs(morphed->primitives[0].morphTargets[0].positionDeltas[2].y - 1.0F) <
                       1.0e-6F,
               "glTF position morph deltas retain target-major vertex order");
        expect(morphed->instances[0].morphWeights.size() == 1 &&
                   std::abs(morphed->instances[0].morphWeights[0] - 0.75F) < 1.0e-6F,
               "glTF node morph weights override mesh defaults");
    }

    const auto texturedPath =
        std::filesystem::path(AETHER_TEST_FIXTURES) / "textured-triangle.gltf";
    auto textured = aether::mesh::GltfLoader::load(texturedPath);
    expect(textured.has_value(), "Data-URI textured glTF fixture loads locally");
    if (textured) {
        expect(textured->images.size() == 1 && !textured->images[0].bytes.empty(),
               "glTF encoded image bytes are retained");
        const auto& uvTransform = textured->materials[1].uvTransforms[0];
        expect(std::abs(uvTransform.scale.x - 2.0F) < 1.0e-6F &&
                   std::abs(uvTransform.scale.y - 0.5F) < 1.0e-6F &&
                   std::abs(uvTransform.offset.x - 0.25F) < 1.0e-6F &&
                   std::abs(uvTransform.rotation - 0.5F) < 1.0e-6F,
               "KHR_texture_transform parameters are retained per texture slot");
        expect(
            textured->textures.size() == 1 &&
                textured->textures[0].mipFilter == aether::mesh::SamplerMipFilter::linear &&
                textured->textures[0].addressU == aether::mesh::SamplerAddressMode::clampToEdge &&
                textured->textures[0].addressV == aether::mesh::SamplerAddressMode::mirroredRepeat,
            "glTF sampler filtering and address modes are retained");
        expect(textured->materials[1].baseColorTexture == 0,
               "glTF material texture binding is retained");
        const simd_float4 tangent = textured->primitives[0].vertices[0].tangent;
        expect(simd_length(simd_float3{tangent.x, tangent.y, tangent.z}) > 0.99F,
               "Missing glTF tangents are generated from UV gradients");
    }
}

void testNativeGltfExporter() {
    const auto fixture = std::filesystem::path(AETHER_TEST_FIXTURES) / "textured-triangle.gltf";
    auto asset = aether::mesh::GltfLoader::load(fixture);
    expect(asset.has_value(), "Native GLB export fixture loads");
    if (!asset)
        return;
    asset->primitives[0].vertexColors = {simd_make_float3(1.0F, 0.0F, 0.0F),
                                         simd_make_float3(0.0F, 1.0F, 0.0F),
                                         simd_make_float3(0.0F, 0.0F, 1.0F)};
    aether::mesh::MeshInstance second = asset->instances.front();
    second.name = "Translated instance";
    second.worldTransform.columns[3].x = 2.0F;
    asset->instances.push_back(second);

    const auto firstPath =
        std::filesystem::temp_directory_path() / "aether-native-export-first.glb";
    const auto secondPath =
        std::filesystem::temp_directory_path() / "aether-native-export-second.glb";
    auto first = aether::mesh::GltfExporter::writeGlb(*asset, firstPath);
    auto secondExport = aether::mesh::GltfExporter::writeGlb(*asset, secondPath);
    expect(first.has_value() && secondExport.has_value(),
           "Native GLB exporter writes a textured static asset");
    if (first && secondExport) {
        expect(first->vertices == 3 && first->triangles == 1 && first->instances == 2 &&
                   first->images == 1,
               "Native GLB report describes exported geometry, instances, and images");
        std::ifstream firstStream(firstPath, std::ios::binary);
        std::ifstream secondStream(secondPath, std::ios::binary);
        const std::vector<char> firstBytes((std::istreambuf_iterator<char>(firstStream)), {});
        const std::vector<char> secondBytes((std::istreambuf_iterator<char>(secondStream)), {});
        expect(firstBytes == secondBytes, "Native GLB output is byte-for-byte deterministic");
        auto roundTrip = aether::mesh::GltfLoader::load(firstPath);
        expect(roundTrip.has_value(), "Native GLB re-imports through the strict loader");
        if (roundTrip) {
            expect(roundTrip->primitives.size() == 1 && roundTrip->instances.size() == 2 &&
                       roundTrip->images.size() == 1 && roundTrip->textures.size() == 1,
                   "Native GLB preserves primitives, instances, and embedded texture resources");
            const bool colorsMatch =
                roundTrip->primitives[0].vertexColors.size() ==
                    asset->primitives[0].vertexColors.size() &&
                std::ranges::equal(
                    roundTrip->primitives[0].vertexColors, asset->primitives[0].vertexColors,
                    [](simd_float3 left, simd_float3 right) { return simd_all(left == right); });
            expect(colorsMatch, "Native GLB preserves linear RGB vertex colors");
            expect(std::abs(roundTrip->instances[1].worldTransform.columns[3].x - 2.0F) < 1.0e-6F,
                   "Native GLB preserves flat instance transforms");
            const auto& material = roundTrip->materials[roundTrip->primitives[0].materialIndex];
            expect(material.baseColorTexture.has_value() &&
                       std::abs(material.uvTransforms[0].rotation - 0.5F) < 1.0e-6F,
                   "Native GLB preserves PBR texture bindings and UV transforms");
        }
    }

    auto animated = aether::mesh::GltfLoader::load(std::filesystem::path(AETHER_TEST_FIXTURES) /
                                                   "animated-triangle.gltf");
    expect(animated.has_value() &&
               !aether::mesh::GltfExporter::writeGlb(*animated, firstPath).has_value(),
           "Native reconstruction export explicitly rejects animation");
    auto degenerate = *asset;
    degenerate.primitives[0].indices = {0, 0, 1};
    expect(!aether::mesh::GltfExporter::writeGlb(degenerate, firstPath).has_value(),
           "Native GLB export rejects degenerate triangle indices");
    auto invalidImage = *asset;
    invalidImage.images[0].bytes.assign(8, std::byte{0});
    expect(!aether::mesh::GltfExporter::writeGlb(invalidImage, firstPath).has_value(),
           "Native GLB export rejects unsupported encoded image data");
    std::filesystem::remove(firstPath);
    std::filesystem::remove(secondPath);
}

void testMeshAnimation() {
    aether::mesh::MeshAsset asset;
    asset.nodes.resize(2);
    asset.nodes[0].name = "Root";
    asset.nodes[0].children = {1};
    asset.nodes[1].name = "Child";
    asset.nodes[1].parentIndex = 0;
    asset.nodes[1].localTransform.translation = {0.0F, 2.0F, 0.0F};

    aether::mesh::AnimationClip clip;
    clip.name = "Motion";
    clip.durationSeconds = 1.0F;
    aether::mesh::AnimationChannel translation;
    translation.nodeIndex = 0;
    translation.path = aether::mesh::AnimationPath::translation;
    translation.interpolation = aether::mesh::AnimationInterpolation::linear;
    translation.keyTimes = {0.0F, 1.0F};
    translation.values = {simd_float4{0.0F, 0.0F, 0.0F, 0.0F}, simd_float4{4.0F, 0.0F, 0.0F, 0.0F}};
    aether::mesh::AnimationChannel scale;
    scale.nodeIndex = 1;
    scale.path = aether::mesh::AnimationPath::scale;
    scale.interpolation = aether::mesh::AnimationInterpolation::cubicSpline;
    scale.keyTimes = {0.0F, 1.0F};
    scale.values = {simd_float4{}, simd_float4{1.0F, 1.0F, 1.0F, 0.0F}, simd_float4{},
                    simd_float4{}, simd_float4{3.0F, 3.0F, 3.0F, 0.0F}, simd_float4{}};
    clip.channels = {translation, scale};
    asset.animations.push_back(clip);

    const auto sampled = aether::mesh::sampleAnimation(asset, 0, 0.5F, false);
    expect(sampled.has_value(), "Mesh animation samples valid LINEAR and CUBICSPLINE channels");
    if (sampled) {
        expect(std::abs((*sampled)[0].translation.x - 2.0F) < 1.0e-6F &&
                   std::abs((*sampled)[1].scale.x - 2.0F) < 1.0e-6F,
               "Mesh animation interpolation produces expected midpoint values");
        const auto worlds = aether::mesh::resolveWorldTransforms(asset, *sampled);
        expect(worlds.has_value(), "Animated local transforms resolve through hierarchy");
        if (worlds) {
            const auto childOrigin = simd_mul((*worlds)[1], simd_float4{0, 0, 0, 1});
            expect(std::abs(childOrigin.x - 2.0F) < 1.0e-6F &&
                       std::abs(childOrigin.y - 2.0F) < 1.0e-6F,
                   "Animated parent transform affects child world matrix");
        }
    }
    const auto looped = aether::mesh::sampleAnimation(asset, 0, 1.25F, true);
    expect(looped.has_value() && std::abs((*looped)[0].translation.x - 1.0F) < 1.0e-6F,
           "Looping animation wraps deterministically");
    const auto clamped = aether::mesh::sampleAnimation(asset, 0, 2.0F, false);
    expect(clamped.has_value() && std::abs((*clamped)[0].translation.x - 4.0F) < 1.0e-6F,
           "Non-looping animation clamps to final key");

    asset.nodes[0].parentIndex = 1;
    std::vector<aether::scene::Transform> cyclicLocals;
    cyclicLocals.reserve(asset.nodes.size());
    for (const auto& node : asset.nodes)
        cyclicLocals.push_back(node.localTransform);
    expect(!aether::mesh::resolveWorldTransforms(asset, cyclicLocals).has_value(),
           "Animation world resolution rejects hierarchy cycles");
}

void testClusteredLighting() {
    aether::scene::Camera camera;
    camera.infiniteFarPlane = false;
    camera.nearPlane = 0.1F;
    camera.farPlane = 100.0F;
    const auto projection = camera.projectionMatrix(16.0F / 9.0F);
    expect(projection.has_value(), "Clustered-light test camera projection is valid");
    if (!projection)
        return;
    aether::scene::Light sun;
    sun.type = aether::scene::LightType::directional;
    sun.direction = {-0.4F, -1.0F, -0.2F};
    sun.intensity = 3.0F;
    aether::scene::Light point;
    point.type = aether::scene::LightType::point;
    point.position = {0.0F, 0.0F, -5.0F};
    point.range = 1.0F;
    aether::scene::ClusterGridConfig config;
    config.columns = 4;
    config.rows = 2;
    config.depthSlices = 4;
    config.nearDepth = camera.nearPlane;
    config.farDepth = camera.farPlane;
    const auto lists = aether::scene::buildClusteredLightLists(
        {sun, point}, matrix_identity_float4x4, *projection, config);
    expect(lists.has_value(), "Directional and point lights build bounded cluster lists");
    if (lists) {
        expect(lists->clusters.size() == 32,
               "Cluster list dimensions produce the exact configured cell count");
        expect(lists->lightIndices.size() >= 32, "Directional light is assigned to every cluster");
        expect(std::ranges::count(lists->lightIndices, 0U) == 32,
               "Directional cluster assignment is complete and non-duplicated");
        expect(std::ranges::count(lists->lightIndices, 1U) > 0 &&
                   std::ranges::count(lists->lightIndices, 1U) < 32,
               "Finite point light is culled to a cluster subset");
    }
    config.maximumLightReferences = 1;
    expect(!aether::scene::buildClusteredLightLists({sun}, matrix_identity_float4x4, *projection,
                                                    config)
                .has_value(),
           "Cluster light-reference overflow fails explicitly");
    point.range = 0.0F;
    expect(!aether::scene::validateLight(point).has_value(),
           "Local lights reject non-positive range");
}

void testImageBasedLighting() {
    aether::scene::EquirectangularEnvironment environment;
    environment.width = 8;
    environment.height = 4;
    environment.linearRgb.assign(32, simd_float3{2.0F, 1.0F, 0.5F});
    const auto sampled = aether::scene::sampleEnvironment(environment, {1.0F, 0.0F, 0.0F});
    expect(sampled.has_value() && simd_length(*sampled - simd_float3{2.0F, 1.0F, 0.5F}) < 1.0e-6F,
           "Equirectangular HDR sampling preserves constant radiance");
    aether::scene::IblPreprocessConfig config;
    config.irradianceSize = 2;
    config.specularSize = 4;
    config.specularMipCount = 3;
    config.brdfLutSize = 4;
    config.diffuseSamples = 64;
    config.specularSamples = 64;
    config.brdfSamples = 64;
    const auto ibl = aether::scene::preprocessImageBasedLighting(environment, config);
    expect(ibl.has_value(), "Bounded deterministic IBL preprocessing succeeds");
    if (ibl) {
        expect(ibl->irradiance.linearRgb.size() == 24 && ibl->prefilteredSpecular.size() == 3 &&
                   ibl->prefilteredSpecular[0].linearRgb.size() == 96 && ibl->brdfLut.size() == 16,
               "IBL outputs have exact configured cube/mip/LUT dimensions");
        expect(std::abs(ibl->irradiance.linearRgb[0].x - 2.0F * 3.14159265F) < 1.0e-3F,
               "Cosine irradiance convolution integrates constant radiance to pi");
        expect(simd_length(ibl->prefilteredSpecular.back().linearRgb[0] -
                           simd_float3{2.0F, 1.0F, 0.5F}) < 1.0e-4F,
               "GGX prefilter preserves a constant environment at every roughness");
        expect(std::ranges::all_of(ibl->brdfLut,
                                   [](simd_float2 value) {
                                       return std::isfinite(value.x) && std::isfinite(value.y) &&
                                              value.x >= 0.0F && value.y >= 0.0F;
                                   }),
               "Split-sum BRDF LUT contains finite non-negative coefficients");
    }
    config.maximumOutputTexels = 1;
    expect(!aether::scene::preprocessImageBasedLighting(environment, config).has_value(),
           "IBL output texel budget is enforced before allocation");
    environment.linearRgb[0].x = std::numeric_limits<float>::infinity();
    expect(!aether::scene::preprocessImageBasedLighting(environment, {}).has_value(),
           "IBL preprocessing rejects non-finite HDR pixels");
}

void testDirectionalShadows() {
    aether::scene::Camera camera;
    camera.nearPlane = 0.1F;
    camera.infiniteFarPlane = true;
    aether::scene::DirectionalShadowConfig config;
    config.cascadeCount = 4;
    config.resolution = 1024;
    config.maximumDistance = 100.0F;
    config.splitLambda = 0.7F;
    const auto cascades = aether::scene::buildDirectionalShadowCascades(
        camera, aether::scene::Transform::identity(), 16.0F / 9.0F,
        simd_float3{-0.4F, -1.0F, -0.6F}, config);
    expect(cascades.has_value(), "Directional shadow cascades build for perspective camera");
    if (cascades) {
        expect(cascades->splitDepths.size() == 4 && cascades->worldToShadowClip.size() == 4,
               "Directional shadow output count matches configured cascades");
        expect(std::ranges::is_sorted(cascades->splitDepths) &&
                   cascades->splitDepths.front() > camera.nearPlane &&
                   std::abs(cascades->splitDepths.back() - 100.0F) < 1.0e-4F,
               "Practical cascade splits are increasing and reach shadow distance");
        expect(std::ranges::all_of(cascades->worldToShadowClip,
                                   [](const auto& matrix) {
                                       return std::isfinite(simd_determinant(matrix)) &&
                                              std::abs(simd_determinant(matrix)) > 1.0e-12F;
                                   }),
               "Directional shadow matrices are finite and invertible");
    }
    config.splitLambda = -0.1F;
    expect(
        !aether::scene::buildDirectionalShadowCascades(camera, aether::scene::Transform::identity(),
                                                       1.0F, simd_float3{0.0F, -1.0F, 0.0F}, config)
             .has_value(),
        "Directional shadows reject invalid split distribution");
    config.splitLambda = 0.5F;
    config.cascadeCount = 9;
    expect(
        !aether::scene::buildDirectionalShadowCascades(camera, aether::scene::Transform::identity(),
                                                       1.0F, simd_float3{0.0F, -1.0F, 0.0F}, config)
             .has_value(),
        "Directional shadows enforce bounded cascade count");
}

void testLocalShadowProjections() {
    aether::scene::Light spot;
    spot.type = aether::scene::LightType::spot;
    spot.position = {1.0F, 2.0F, 3.0F};
    spot.direction = simd_normalize(simd_float3{-0.25F, -0.5F, -1.0F});
    spot.range = 25.0F;
    const auto spotProjection = aether::scene::buildSpotShadowProjection(spot);
    expect(spotProjection.has_value(), "Spot shadow projection builds for a valid spot light");
    if (spotProjection) {
        const auto world = spot.position + spot.direction * 5.0F;
        const auto clip = simd_mul(spotProjection->worldToShadowClip,
                                   simd_float4{world.x, world.y, world.z, 1.0F});
        const auto ndc = clip.xyz / clip.w;
        expect(std::abs(ndc.x) < 1.0e-4F && std::abs(ndc.y) < 1.0e-4F && ndc.z >= 0.0F &&
                   ndc.z <= 1.0F,
               "Spot shadow axis maps to the Metal viewport center and depth range");
        expect(std::isfinite(simd_determinant(spotProjection->worldToShadowClip)) &&
                   std::abs(simd_determinant(spotProjection->worldToShadowClip)) > 1.0e-12F,
               "Spot shadow matrix is finite and invertible");
    }

    aether::scene::Light point;
    point.type = aether::scene::LightType::point;
    point.position = {-2.0F, 0.5F, 4.0F};
    point.range = 15.0F;
    const auto pointProjection = aether::scene::buildPointShadowProjection(point);
    expect(pointProjection.has_value(), "Point shadow projection builds for a valid point light");
    if (pointProjection) {
        constexpr std::array directions{simd_float3{1, 0, 0}, simd_float3{-1, 0, 0},
                                        simd_float3{0, 1, 0}, simd_float3{0, -1, 0},
                                        simd_float3{0, 0, 1}, simd_float3{0, 0, -1}};
        bool validFaces = true;
        for (std::size_t face = 0; face < directions.size(); ++face) {
            const auto& matrix = pointProjection->worldToShadowClip[face];
            const auto world = point.position + directions[face] * 3.0F;
            const auto clip = simd_mul(matrix, simd_float4{world.x, world.y, world.z, 1.0F});
            const auto ndc = clip.xyz / clip.w;
            validFaces = validFaces && std::isfinite(simd_determinant(matrix)) &&
                         std::abs(simd_determinant(matrix)) > 1.0e-12F &&
                         std::abs(ndc.x) < 1.0e-4F && std::abs(ndc.y) < 1.0e-4F && ndc.z >= 0.0F &&
                         ndc.z <= 1.0F;
        }
        expect(validFaces,
               "All point shadow faces are finite, invertible, centered, and Metal-depth valid");
    }

    aether::scene::LocalShadowConfig invalid;
    invalid.resolution = 0;
    expect(!aether::scene::buildSpotShadowProjection(spot, invalid).has_value(),
           "Local shadows reject zero resolution");
    invalid.resolution = 1024;
    invalid.nearPlane = point.range;
    expect(!aether::scene::buildPointShadowProjection(point, invalid).has_value(),
           "Local shadows reject a near plane outside the light range");
    expect(!aether::scene::buildSpotShadowProjection(point).has_value() &&
               !aether::scene::buildPointShadowProjection(spot).has_value(),
           "Local shadow builders reject the wrong light type");

    std::vector<aether::scene::Light> lights;
    for (std::uint32_t index = 0; index < 7; ++index) {
        auto light = index % 2 == 0 ? spot : point;
        lights.push_back(light);
    }
    const auto allocations = aether::scene::selectLocalShadowLights(lights);
    expect(allocations.has_value() && allocations->size() == 6,
           "Local shadow admission enforces four spot and two point budgets");
    if (allocations) {
        expect(allocations->front().sourceLightIndex == 0 && allocations->front().baseSlice == 0 &&
                   allocations->back().sourceLightIndex == 6 &&
                   allocations->back().baseSlice + allocations->back().sliceCount == 16,
               "Local shadow admission is stable and remains within sixteen slices");
    }
    lights[0].range = -1.0F;
    expect(!aether::scene::selectLocalShadowLights(lights).has_value(),
           "Local shadow admission rejects invalid source lights");
}

void testSha256() {
    constexpr std::string_view value = "abc";
    const auto bytes = std::as_bytes(std::span(value.data(), value.size()));
    const auto digest = aether::package::Sha256::hash(bytes);
    expect(aether::package::Sha256::hex(digest) ==
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
           "SHA-256 matches the standard abc vector");
}

void testAetherPackage() {
    const auto path = std::filesystem::temp_directory_path() / "aether-package-test.aether";
    constexpr std::string_view metadata = "{\"name\":\"fixture\"}";
    std::vector<std::byte> gaussians(16'384);
    for (std::size_t index = 0; index < gaussians.size(); ++index) {
        gaussians[index] = static_cast<std::byte>(index % 251U);
    }
    aether::package::PackageWriter writer;
    expect(writer
               .addChunk(aether::package::ChunkType::metadata,
                         std::as_bytes(std::span(metadata.data(), metadata.size())))
               .has_value(),
           "Metadata chunk is accepted");
    expect(writer.addChunk(aether::package::ChunkType::baseGaussians, gaussians).has_value(),
           "Gaussian chunk is accepted");
    expect(writer.write(path).has_value(), "AETHER package is written atomically");

    auto reader = aether::package::PackageReader::open(path);
    expect(reader.has_value(), "AETHER package header, table, and content hash validate");
    if (reader) {
        expect(reader->info().chunks.size() == 2, "AETHER chunk table round-trips");
        auto decoded = reader->readChunk(aether::package::ChunkType::baseGaussians);
        expect(decoded.has_value() && *decoded == gaussians,
               "Zstandard chunk decompresses and verifies its hash");
        expect(reader->info().chunks[1].storedBytes < reader->info().chunks[1].uncompressedBytes,
               "Compressible Gaussian fixture is stored with compression");
    }

    {
        std::fstream corrupt(path, std::ios::binary | std::ios::in | std::ios::out);
        corrupt.seekp(80);
        const char changed = '\x55';
        corrupt.write(&changed, 1);
    }
    expect(!aether::package::PackageReader::open(path).has_value(),
           "Whole-package hash rejects corrupted content");
    std::filesystem::remove(path);
}

void testGaussianPly() {
    const auto path = std::filesystem::temp_directory_path() / "aether-gaussian-test.ply";
    {
        std::ofstream stream(path, std::ios::binary);
        stream << "ply\n"
                  "format ascii 1.0\n"
                  "comment deterministic AETHER fixture\n"
                  "element vertex 1\n"
                  "property float x\n"
                  "property float y\n"
                  "property float z\n"
                  "property float f_dc_0\n"
                  "property float f_dc_1\n"
                  "property float f_dc_2\n"
                  "property float opacity\n"
                  "property float scale_0\n"
                  "property float scale_1\n"
                  "property float scale_2\n"
                  "property float rot_0\n"
                  "property float rot_1\n"
                  "property float rot_2\n"
                  "property float rot_3\n"
                  "property float confidence\n"
                  "end_header\n"
                  "0 0 2 1 0 0 5 -2 -2 -2 2 0 0 0 0.75\n";
    }
    auto asset = aether::gaussian::PlyLoader::load(path);
    expect(asset.has_value() && asset->gaussians.size() == 1, "Strict 3DGS PLY fixture loads");
    if (asset) {
        expect(asset->sphericalHarmonicDegree == 0, "PLY DC-only SH degree is detected");
        expect(asset->diagnostics.size() == 1, "Unknown scalar property produces a diagnostic");
        expect(std::abs(asset->gaussians[0].rotation[0] - 1.0F) < 1.0e-6F,
               "PLY quaternion is normalized");
        auto encoded = aether::gaussian::GaussianCodec::encode(*asset);
        expect(encoded.has_value() &&
                   encoded->size() == aether::gaussian::GaussianCodec::headerBytes +
                                          aether::gaussian::GaussianCodec::recordBytes,
               "Canonical Gaussian chunk has a fixed, compiler-independent record size");
        if (encoded) {
            auto decoded = aether::gaussian::GaussianCodec::decode(*encoded);
            expect(decoded.has_value() && decoded->gaussians[0].position[2] == 2.0F,
                   "Canonical Gaussian chunk round-trips through strict decoding");
            (*encoded)[0] = std::byte{0};
            expect(!aether::gaussian::GaussianCodec::decode(*encoded).has_value(),
                   "Canonical Gaussian decoder rejects invalid magic");
        }

        aether::gaussian::ReferenceCamera camera;
        camera.width = 9;
        camera.height = 9;
        camera.focalX = 8.0F;
        camera.focalY = 8.0F;
        camera.centerX = 4.5F;
        camera.centerY = 4.5F;
        auto image = aether::gaussian::ReferenceRasterizer::render(*asset, camera);
        expect(image.has_value(), "CPU Gaussian reference rasterizer accepts a calibrated camera");
        if (image) {
            constexpr std::size_t center = 4 * 9 + 4;
            expect(image->color[center][3] > 0.9F,
                   "CPU Gaussian reference produces opaque center coverage");
            expect(std::abs(image->depth[center] - 2.0F) < 1.0e-6F,
                   "CPU Gaussian reference writes first-hit depth");
            expect(image->ids[center] == 1, "CPU Gaussian reference writes a stable source ID");
        }

        auto shAsset = *asset;
        shAsset.sphericalHarmonicDegree = 1;
        shAsset.gaussians[0].restCount = 9;
        shAsset.gaussians[0].rest[1] = 0.25F;
        auto frontView = aether::gaussian::ReferenceRasterizer::render(shAsset, camera);
        camera.cameraWorldPosition = {0.0F, 0.0F, 4.0F};
        auto backView = aether::gaussian::ReferenceRasterizer::render(shAsset, camera);
        if (frontView && backView) {
            constexpr std::size_t center = 4 * 9 + 4;
            const float expectedFront = 0.5F + 0.28209479177387814F + 0.25F * 0.4886025119029199F;
            expect(std::abs(frontView->color[center][0] / frontView->color[center][3] -
                            expectedFront) < 1.0e-4F,
                   "CPU Gaussian reference evaluates degree-1 SH in GraphDECO ordering");
            expect(frontView->color[center][0] > backView->color[center][0],
                   "CPU Gaussian SH appearance changes with world-space view direction");
        }
    }
    aether::gaussian::PlyLimits limits;
    limits.maximumGaussians = 0;
    expect(!aether::gaussian::PlyLoader::load(path, limits).has_value(),
           "PLY Gaussian allocation limit is enforced before payload allocation");
    std::filesystem::remove(path);

    const auto binaryPath =
        std::filesystem::temp_directory_path() / "aether-gaussian-binary-test.ply";
    {
        std::ofstream stream(binaryPath, std::ios::binary);
        stream << "ply\n"
                  "format binary_little_endian 1.0\n"
                  "element vertex 1\n"
                  "property float x\nproperty float y\nproperty float z\n"
                  "property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n"
                  "property float opacity\n"
                  "property float scale_0\nproperty float scale_1\nproperty float scale_2\n"
                  "property float rot_0\nproperty float rot_1\nproperty float rot_2\nproperty "
                  "float rot_3\n"
                  "end_header\n";
        constexpr std::array values{0.0F,  0.0F,  3.0F,  0.0F, 0.0F, 0.0F, 2.0F,
                                    -1.0F, -1.0F, -1.0F, 1.0F, 0.0F, 0.0F, 0.0F};
        for (const float value : values) {
            const std::uint32_t bits = std::bit_cast<std::uint32_t>(value);
            for (std::size_t byte = 0; byte < sizeof(bits); ++byte) {
                const auto output = static_cast<char>((bits >> (byte * 8U)) & 0xffU);
                stream.write(&output, 1);
            }
        }
    }
    const auto binaryAsset = aether::gaussian::PlyLoader::load(binaryPath);
    expect(binaryAsset.has_value() && binaryAsset->gaussians[0].position[2] == 3.0F,
           "Binary-little-endian 3DGS PLY loads deterministically");
    std::filesystem::remove(binaryPath);
}

} // namespace

int runTests() {
    testErrors();
    testResourceLocator();
    testDiagnostics();
    testSparseCoverageValidation();
    testOracleTsdfReconstruction();
    testProxyMeshContract();
    testProfiler();
    testJobSystem();
    testRenderGraph();
    testSceneTransforms();
    testCameraProjection();
    testCameraController();
    testCameraPath();
    testGltfLoader();
    testNativeGltfExporter();
    testMeshAnimation();
    testClusteredLighting();
    testImageBasedLighting();
    testDirectionalShadows();
    testLocalShadowProjections();
    testSha256();
    testAetherPackage();
    testGaussianPly();
    if (failures == 0) {
        std::cout << "All AETHER foundation tests passed\n";
    }
    return failures == 0 ? 0 : 1;
}

int main() noexcept {
    try {
        return runTests();
    } catch (const std::exception& error) {
        std::cerr << "Unhandled AETHER test failure: " << error.what() << '\n';
    } catch (...) {
        std::cerr << "Unhandled AETHER test failure\n";
    }
    return 1;
}
