#include <aether/reconstruction/DenseTsdfVolume.hpp>
#include <aether/reconstruction/IncrementalSparseTsdfMesher.hpp>
#include <aether/reconstruction/RecordedProviders.hpp>
#include <aether/reconstruction/SparseTsdfVolume.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <numbers>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

int failures{};

struct Evidence final {
    std::size_t parityObservedVoxels{};
    std::size_t parityAllocatedBlocks{};
    std::size_t parityMeshVertices{};
    std::size_t parityMeshTriangles{};
    std::uint64_t roomLogicalVoxels{};
    aether::reconstruction::SparseTsdfStatistics room;
    std::size_t incrementalDirtyBlocks{};
    std::size_t incrementalUpdates{};
    std::size_t incrementalPatches{};
    std::size_t incrementalTriangles{};
};

Evidence evidence;

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

aether::capture::CapturePacket makePlanePacket(float planeDepth = 1.0F) {
    constexpr std::uint32_t width = 64;
    constexpr std::uint32_t height = 64;
    std::vector<std::byte> color(static_cast<std::size_t>(width) * height * 3);
    for (std::size_t index = 0; index < color.size() / 3; ++index) {
        color[index * 3] = std::byte{128};
        color[index * 3 + 1] = std::byte{64};
        color[index * 3 + 2] = std::byte{32};
    }
    std::vector<std::byte> depth(static_cast<std::size_t>(width) * height * sizeof(float));
    for (std::size_t index = 0; index < static_cast<std::size_t>(width) * height; ++index)
        std::memcpy(depth.data() + index * sizeof(float), &planeDepth, sizeof(float));

    aether::capture::CapturePacket packet;
    packet.frameId = 1;
    packet.sourceId = "sparse-plane";
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
    return packet;
}

void applyTestPose(aether::capture::CapturePacket& packet) {
    constexpr double halfAngleRadians = 6.0 * std::numbers::pi / 180.0;
    packet.cameraToWorld = aether::capture::RigidPose{
        {std::cos(halfAngleRadians), 0.0, std::sin(halfAngleRadians), 0.0},
        {0.02, -0.03, 0.01},
    };
}

struct Observation final {
    aether::reconstruction::PoseEstimate pose;
    aether::reconstruction::DepthObservation depth;
};

Observation providers(aether::capture::CapturePacket& packet) {
    aether::reconstruction::RecordedPoseProvider poseProvider;
    aether::reconstruction::RecordedRgbdDepthProvider depthProvider;
    auto pose = poseProvider.estimate(packet);
    if (!pose)
        throw std::runtime_error(pose.error().describe());
    auto depth = depthProvider.estimate(packet, *pose);
    if (!depth)
        throw std::runtime_error(depth.error().describe());
    return {*pose, *depth};
}

aether::reconstruction::DenseTsdfConfig planeConfig() {
    aether::reconstruction::DenseTsdfConfig config;
    config.dimensions = {21, 21, 17};
    config.originMetres = {-0.4, -0.4, 0.68};
    config.voxelSizeMetres = 0.04;
    config.truncationDistanceMetres = 0.08;
    config.minimumDepthMetres = 0.1;
    config.maximumDepthMetres = 2.0;
    return config;
}

bool sameVoxel(const aether::reconstruction::TsdfVoxel& left,
               const aether::reconstruction::TsdfVoxel& right) {
    return left.distance == right.distance && left.weight == right.weight &&
           left.color == right.color && left.observations == right.observations;
}

bool sameMesh(const aether::mesh::MeshAsset& left, const aether::mesh::MeshAsset& right) {
    if (left.primitives.size() != 1 || right.primitives.size() != 1)
        return false;
    const auto& a = left.primitives.front();
    const auto& b = right.primitives.front();
    if (a.indices != b.indices || a.vertices.size() != b.vertices.size() ||
        a.vertexColors.size() != b.vertexColors.size())
        return false;
    for (std::size_t index = 0; index < a.vertices.size(); ++index) {
        if (simd_any(a.vertices[index].position != b.vertices[index].position) ||
            simd_any(a.vertices[index].normal != b.vertices[index].normal) ||
            simd_any(a.vertexColors[index] != b.vertexColors[index]))
            return false;
    }
    return true;
}

std::size_t triangleCount(const aether::mesh::MeshAsset& mesh) {
    std::size_t result{};
    for (const auto& primitive : mesh.primitives)
        result += primitive.indices.size() / 3;
    return result;
}

bool exactPatchSeams(const aether::mesh::MeshAsset& mesh) {
    std::size_t sharedVertices{};
    for (std::size_t left = 0; left < mesh.primitives.size(); ++left)
        for (std::size_t right = left + 1; right < mesh.primitives.size(); ++right)
            for (const auto& a : mesh.primitives[left].vertices)
                for (const auto& b : mesh.primitives[right].vertices) {
                    const auto delta = a.position - b.position;
                    if (std::abs(delta.x) > 1.0e-6F || std::abs(delta.y) > 1.0e-6F ||
                        std::abs(delta.z) > 1.0e-6F)
                        continue;
                    ++sharedVertices;
                    if (simd_any(a.position != b.position) || simd_any(a.normal != b.normal))
                        return false;
                }
    return sharedVertices > 0;
}

void testIncrementalHaloMeshing() {
    auto packet = makePlanePacket();
    applyTestPose(packet);
    const auto observation = providers(packet);
    aether::reconstruction::SparseTsdfConfig config;
    config.volume = planeConfig();
    config.blockResolution = 4;
    config.maximumBlocks = 1'000;
    auto volume = aether::reconstruction::SparseTsdfVolume::create(config);
    auto mesher = aether::reconstruction::IncrementalSparseTsdfMesher::create();
    expect(volume && mesher, "incremental sparse meshing fixtures should be created");
    if (!volume || !mesher)
        return;
    expect(volume->integrate(packet, observation.pose, observation.depth).has_value(),
           "incremental sparse meshing fixture should integrate");
    const auto snapshot = volume->snapshot();
    const auto dirty = volume->dirtyBlocks();
    const auto full = volume->extractMesh();
    expect(snapshot && full, "incremental meshing should have a sparse field and full reference");
    if (!snapshot || !full)
        return;
    auto updates = mesher->update(*snapshot, dirty);
    expect(updates && !updates->empty() && mesher->generation() == snapshot->generation,
           "dirty sparse blocks should produce completed-generation mesh patches");
    const auto incremental = mesher->mesh();
    expect(triangleCount(incremental) == triangleCount(*full),
           "halo-owned incremental patches should cover every full-extraction triangle exactly");
    expect(exactPatchSeams(incremental),
           "positions and normals shared by adjacent patches should be bit-exact and seamless");
    evidence.incrementalDirtyBlocks = dirty.size();
    evidence.incrementalUpdates = updates ? updates->size() : 0;
    evidence.incrementalPatches = mesher->patchCount();
    evidence.incrementalTriangles = triangleCount(incremental);

    auto deterministic = aether::reconstruction::IncrementalSparseTsdfMesher::create();
    expect(deterministic.has_value(), "independent incremental mesher should be created");
    if (!deterministic)
        return;
    auto repeated = deterministic->update(*snapshot, dirty);
    expect(repeated && deterministic->patchCount() == mesher->patchCount() &&
               triangleCount(deterministic->mesh()) == triangleCount(incremental),
           "independent incremental patch construction should be deterministic");

    aether::reconstruction::IncrementalSparseMesherConfig boundedConfig;
    boundedConfig.maximumPatchesPerUpdate = 1;
    auto bounded = aether::reconstruction::IncrementalSparseTsdfMesher::create(boundedConfig);
    expect(bounded && !bounded->update(*snapshot, dirty) && bounded->patchCount() == 0,
           "patch-budget failure should preserve an empty incremental cache");
    aether::reconstruction::IncrementalSparseMesherConfig voxelBoundedConfig;
    voxelBoundedConfig.maximumPatchVoxels = 8;
    auto voxelBounded =
        aether::reconstruction::IncrementalSparseTsdfMesher::create(voxelBoundedConfig);
    expect(voxelBounded && !voxelBounded->update(*snapshot, dirty) &&
               voxelBounded->patchCount() == 0,
           "patch-voxel budget failure should preserve an empty incremental cache");
    auto malformedSnapshot = *snapshot;
    malformedSnapshot.blocks.push_back(malformedSnapshot.blocks.front());
    auto malformed = aether::reconstruction::IncrementalSparseTsdfMesher::create();
    const std::array<aether::reconstruction::TsdfBlockCoordinate, 1> outsideDirty{{{999, 0, 0}}};
    expect(malformed && !malformed->update(malformedSnapshot, dirty) &&
               !malformed->update(*snapshot, outsideDirty) && malformed->patchCount() == 0,
           "malformed snapshots and out-of-range dirtiness should fail transactionally");

    auto emptySnapshot = *snapshot;
    ++emptySnapshot.generation;
    for (auto& block : emptySnapshot.blocks)
        std::fill(block.voxels.begin(), block.voxels.end(), aether::reconstruction::TsdfVoxel{});
    auto removals = mesher->update(emptySnapshot, dirty);
    expect(removals && mesher->patchCount() == 0 &&
               std::ranges::all_of(
                   *removals, [](const auto& update) { return !update.primitive.has_value(); }),
           "an empty newer generation should explicitly remove every stale patch");
    expect(!mesher->update(*snapshot, dirty) && mesher->patchCount() == 0,
           "a stale snapshot should fail without restoring removed patches");
}

void testDenseParityAndDeterminism() {
    auto packet = makePlanePacket();
    applyTestPose(packet);
    const auto observation = providers(packet);
    const auto config = planeConfig();
    auto dense = aether::reconstruction::DenseTsdfVolume::create(config);
    aether::reconstruction::SparseTsdfConfig sparseConfig;
    sparseConfig.volume = config;
    sparseConfig.blockResolution = 4;
    sparseConfig.maximumBlocks = 1'000;
    auto first = aether::reconstruction::SparseTsdfVolume::create(sparseConfig);
    auto second = aether::reconstruction::SparseTsdfVolume::create(sparseConfig);
    expect(dense.has_value() && first.has_value() && second.has_value(),
           "dense and sparse parity volumes should be created");
    if (!dense || !first || !second)
        return;
    expect(dense->integrate(packet, observation.pose, observation.depth).has_value() &&
               first->integrate(packet, observation.pose, observation.depth).has_value() &&
               second->integrate(packet, observation.pose, observation.depth).has_value(),
           "dense and sparse parity volumes should integrate the same plane");
    expect(first->integrate(packet, observation.pose, observation.depth).has_value() &&
               dense->integrate(packet, observation.pose, observation.depth).has_value(),
           "dense and sparse volumes should preserve repeated-frame saturation behavior");

    std::size_t denseObserved{};
    bool equal = true;
    for (std::uint32_t z = 0; z < config.dimensions[2]; ++z)
        for (std::uint32_t y = 0; y < config.dimensions[1]; ++y)
            for (std::uint32_t x = 0; x < config.dimensions[0]; ++x) {
                const auto index = (static_cast<std::size_t>(z) * config.dimensions[1] + y) *
                                       config.dimensions[0] +
                                   x;
                const auto& denseVoxel = dense->voxels()[index];
                if (denseVoxel.weight <= 0.0F)
                    continue;
                ++denseObserved;
                const auto sparseVoxel = first->voxel(x, y, z);
                equal = equal && sparseVoxel.has_value() && sameVoxel(denseVoxel, *sparseVoxel);
            }
    expect(equal && first->statistics().observedVoxels == denseObserved,
           "sparse fusion must exactly match every observed dense-oracle sample");
    expect(first->statistics().integratedFrames == 2 &&
               first->statistics().lastFrameVoxelUpdates == denseObserved,
           "sparse statistics should report accepted frames and exact updates");
    const auto dirtyBlocks = first->dirtyBlocks();
    expect(!dirtyBlocks.empty() && std::is_sorted(dirtyBlocks.begin(), dirtyBlocks.end()),
           "dirty blocks should be deterministic and ordered");

    auto denseMesh = dense->extractMesh();
    auto sparseMesh = first->extractMesh();
    expect(denseMesh.has_value() && sparseMesh.has_value() && sameMesh(*denseMesh, *sparseMesh),
           "sparse extraction must exactly match the resolved dense-oracle plane mesh");
    evidence.parityObservedVoxels = denseObserved;
    evidence.parityAllocatedBlocks = first->statistics().allocatedBlocks;
    if (sparseMesh) {
        evidence.parityMeshVertices = sparseMesh->primitives.front().vertices.size();
        evidence.parityMeshTriangles = sparseMesh->primitives.front().indices.size() / 3;
    }
    auto secondMesh = second->extractMesh();
    expect(secondMesh.has_value(), "independent deterministic sparse extraction should succeed");
    if (secondMesh) {
        auto onceDense = aether::reconstruction::DenseTsdfVolume::create(config);
        expect(onceDense.has_value() &&
                   onceDense->integrate(packet, observation.pose, observation.depth).has_value(),
               "single-frame dense comparison should integrate");
        auto onceMesh =
            onceDense ? onceDense->extractMesh()
                      : aether::Result<aether::mesh::MeshAsset>(std::unexpected(onceDense.error()));
        expect(onceMesh.has_value() && sameMesh(*onceMesh, *secondMesh),
               "independent single-frame sparse output should be deterministic");
    }
    first->clearDirtyBlocks();
    expect(first->dirtyBlocks().empty() && first->statistics().dirtyBlocks == 0,
           "dirty-block acknowledgement should be explicit");
}

void testRoomScaleLogicalGridAndTransactionalBudgets() {
    aether::reconstruction::SparseTsdfConfig room;
    room.volume = planeConfig();
    room.volume.dimensions = {1001, 1001, 1001};
    room.volume.originMetres = {-5.0, -5.0, 0.0};
    room.volume.voxelSizeMetres = 0.01;
    room.volume.truncationDistanceMetres = 0.04;
    room.blockResolution = 8;
    room.maximumBlocks = 20'000;
    auto sparse = aether::reconstruction::SparseTsdfVolume::create(room);
    auto dense = aether::reconstruction::DenseTsdfVolume::create(room.volume);
    expect(sparse.has_value() && !dense.has_value(),
           "sparse creation should accept a billion-voxel logical room without allocating it");
    if (!sparse)
        return;
    expect(sparse->statistics().allocatedBlocks == 0 && sparse->statistics().voxelPayloadBytes == 0,
           "empty room-scale sparse volume should own no voxel payload");
    auto packet = makePlanePacket();
    const auto observation = providers(packet);
    expect(sparse->integrate(packet, observation.pose, observation.depth).has_value(),
           "room-scale logical grid should integrate a local observation");
    const auto statistics = sparse->statistics();
    const std::uint64_t logicalVoxels = std::uint64_t{1001} * 1001 * 1001;
    expect(statistics.allocatedBlocks > 0 && statistics.observedVoxels > 0 &&
               statistics.allocatedVoxels < logicalVoxels / 100,
           "local room observation should keep more than 99 percent of logical voxels unallocated");
    evidence.roomLogicalVoxels = logicalVoxels;
    evidence.room = statistics;

    auto blockedConfig = room;
    blockedConfig.maximumBlocks = 1;
    auto blocked = aether::reconstruction::SparseTsdfVolume::create(blockedConfig);
    expect(blocked.has_value() &&
               !blocked->integrate(packet, observation.pose, observation.depth).has_value() &&
               blocked->statistics().allocatedBlocks == 0 &&
               blocked->statistics().integratedFrames == 0,
           "resident-budget failure should leave the sparse volume transactionally unchanged");
    auto candidateConfig = room;
    candidateConfig.maximumCandidateBlocksPerFrame = 1;
    auto candidateBlocked = aether::reconstruction::SparseTsdfVolume::create(candidateConfig);
    expect(
        candidateBlocked.has_value() &&
            !candidateBlocked->integrate(packet, observation.pose, observation.depth).has_value() &&
            candidateBlocked->statistics().allocatedBlocks == 0,
        "candidate-budget failure should not allocate partial blocks");

    aether::reconstruction::SparseTsdfConfig extractionConfig;
    extractionConfig.volume = planeConfig();
    extractionConfig.blockResolution = 4;
    extractionConfig.maximumBlocks = 1'000;
    extractionConfig.maximumExtractionVoxels = 64;
    auto extractionBlocked = aether::reconstruction::SparseTsdfVolume::create(extractionConfig);
    expect(extractionBlocked.has_value(), "extraction-budget fixture should be created");
    if (extractionBlocked) {
        const auto integrated =
            extractionBlocked->integrate(packet, observation.pose, observation.depth);
        if (!integrated)
            std::cerr << "FAIL context: " << integrated.error().describe() << '\n';
        expect(integrated.has_value(),
               "extraction-budget fixture should integrate before extraction");
        const auto before = extractionBlocked->statistics();
        const auto mesh = extractionBlocked->extractMesh();
        const auto after = extractionBlocked->statistics();
        expect(!mesh.has_value() && mesh.error().code == aether::ErrorCode::resourceExhausted &&
                   before.allocatedBlocks == after.allocatedBlocks &&
                   before.observedVoxels == after.observedVoxels,
               "dense-snapshot extraction budget should fail without mutating sparse state");
    }
}

struct OutputPaths final {
    std::optional<std::filesystem::path> sparse;
    std::optional<std::filesystem::path> incremental;
};

OutputPaths outputPaths(int argc, char** argv) {
    if (argc == 1)
        return {};
    if ((argc != 3 && argc != 5) || std::string_view(argv[1]) != "--json-output" ||
        (argc == 5 && std::string_view(argv[3]) != "--incremental-json-output"))
        throw std::runtime_error("Usage: AetherSparseTsdfTests [--json-output <path> "
                                 "--incremental-json-output <path>]");
    return {std::filesystem::path(argv[2]),
            argc == 5 ? std::optional<std::filesystem::path>(argv[4]) : std::nullopt};
}

void writeEvidence(const std::filesystem::path& path) {
    const double allocationRatio = static_cast<double>(evidence.room.allocatedVoxels) /
                                   static_cast<double>(evidence.roomLogicalVoxels);
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<double>::max_digits10) << "{\n"
           << "  \"schemaVersion\": 1,\n"
           << "  \"evidenceLevel\": \"E2-fixture\",\n"
           << "  \"backend\": \"deterministic-cpu-block-sparse-tsdf\",\n"
           << "  \"parity\": {\n"
           << "    \"blockResolution\": 4,\n"
           << "    \"cameraPose\": \"translated-and-yaw-rotated\",\n"
           << "    \"repeatedFrames\": 2,\n"
           << "    \"denseObservedVoxels\": " << evidence.parityObservedVoxels << ",\n"
           << "    \"sparseObservedVoxels\": " << evidence.parityObservedVoxels << ",\n"
           << "    \"exactVoxelAgreement\": true,\n"
           << "    \"exactResolvedMeshAgreement\": true,\n"
           << "    \"allocatedBlocks\": " << evidence.parityAllocatedBlocks << ",\n"
           << "    \"meshVertices\": " << evidence.parityMeshVertices << ",\n"
           << "    \"meshTriangles\": " << evidence.parityMeshTriangles << "\n"
           << "  },\n"
           << "  \"roomScaleLogicalGrid\": {\n"
           << "    \"blockResolution\": 8,\n"
           << "    \"dimensions\": [1001, 1001, 1001],\n"
           << "    \"logicalVoxels\": " << evidence.roomLogicalVoxels << ",\n"
           << "    \"allocatedBlocks\": " << evidence.room.allocatedBlocks << ",\n"
           << "    \"allocatedVoxels\": " << evidence.room.allocatedVoxels << ",\n"
           << "    \"observedVoxels\": " << evidence.room.observedVoxels << ",\n"
           << "    \"voxelPayloadBytes\": " << evidence.room.voxelPayloadBytes << ",\n"
           << "    \"allocationRatio\": " << allocationRatio << ",\n"
           << "    \"unallocatedPercent\": " << (1.0 - allocationRatio) * 100.0 << ",\n"
           << "    \"lastFrameCandidateBlocks\": " << evidence.room.lastFrameCandidateBlocks
           << ",\n"
           << "    \"lastFrameVoxelUpdates\": " << evidence.room.lastFrameVoxelUpdates << "\n"
           << "  },\n"
           << "  \"transactionalBudgetFailure\": true,\n"
           << "  \"limitations\": [\n"
           << "    \"Synthetic plane evidence is not real-capture E3 accuracy evidence.\",\n"
           << "    \"Extraction uses a bounded dense snapshot of the allocated span; incremental "
              "block meshing remains open.\"\n"
           << "  ]\n"
           << "}\n";
    std::error_code error;
    std::filesystem::create_directories(path.parent_path(), error);
    if (error)
        throw std::runtime_error("Unable to create sparse TSDF evidence directory");
    auto temporary = path;
    temporary += ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream << output.str();
    stream.close();
    if (!stream)
        throw std::runtime_error("Unable to write sparse TSDF evidence");
    std::filesystem::rename(temporary, path, error);
    if (error)
        throw std::runtime_error("Unable to publish sparse TSDF evidence atomically");
}

void writeIncrementalEvidence(const std::filesystem::path& path) {
    std::ostringstream output;
    output << "{\n"
           << "  \"schemaVersion\": 1,\n"
           << "  \"evidenceLevel\": \"E2-fixture\",\n"
           << "  \"backend\": \"halo-owned-incremental-sparse-tsdf-mesher\",\n"
           << "  \"dirtyBlocks\": " << evidence.incrementalDirtyBlocks << ",\n"
           << "  \"patchUpdates\": " << evidence.incrementalUpdates << ",\n"
           << "  \"residentPatches\": " << evidence.incrementalPatches << ",\n"
           << "  \"incrementalTriangles\": " << evidence.incrementalTriangles << ",\n"
           << "  \"fullExtractionTriangles\": " << evidence.parityMeshTriangles << ",\n"
           << "  \"exactTriangleCoverage\": true,\n"
           << "  \"bitExactSharedPositionsAndNormals\": true,\n"
           << "  \"transactionalBudgetFailure\": true,\n"
           << "  \"explicitPatchRemoval\": true,\n"
           << "  \"staleGenerationRejection\": true,\n"
           << "  \"limitations\": [\n"
           << "    \"Patch extraction currently executes on the CPU from immutable sparse "
              "snapshots.\",\n"
           << "    \"Asynchronous scheduling and GPU-resident Marching Cubes remain open.\"\n"
           << "  ]\n"
           << "}\n";
    std::error_code error;
    std::filesystem::create_directories(path.parent_path(), error);
    if (error)
        throw std::runtime_error("Unable to create incremental meshing evidence directory");
    auto temporary = path;
    temporary += ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream << output.str();
    stream.close();
    if (!stream)
        throw std::runtime_error("Unable to write incremental meshing evidence");
    std::filesystem::rename(temporary, path, error);
    if (error)
        throw std::runtime_error("Unable to publish incremental meshing evidence atomically");
}

void testHostileConfiguration() {
    aether::reconstruction::SparseTsdfConfig config;
    config.volume = planeConfig();
    config.blockResolution = 3;
    expect(!aether::reconstruction::SparseTsdfVolume::create(config).has_value(),
           "non-power-of-two block resolution should be rejected");
    config.blockResolution = 8;
    config.maximumBlocks = std::numeric_limits<std::size_t>::max();
    expect(!aether::reconstruction::SparseTsdfVolume::create(config).has_value(),
           "overflowing resident voxel budgets should be rejected");

    auto packet = makePlanePacket();
    const auto observation = providers(packet);

    aether::reconstruction::SparseTsdfConfig disjoint;
    disjoint.volume = planeConfig();
    disjoint.volume.dimensions = {1001, 1001, 1001};
    disjoint.volume.originMetres = {1'000'000.0, 1'000'000.0, 1'000'000.0};
    disjoint.blockResolution = 8;
    disjoint.maximumBlocks = 20'000;
    auto outside = aether::reconstruction::SparseTsdfVolume::create(disjoint);
    expect(outside.has_value(), "a distant logical sparse volume should be valid");
    if (outside) {
        const auto integrated = outside->integrate(packet, observation.pose, observation.depth);
        expect(!integrated.has_value() &&
                   integrated.error().code == aether::ErrorCode::invalidArgument &&
                   outside->statistics().allocatedBlocks == 0 &&
                   outside->statistics().integratedFrames == 0,
               "a depth ray disjoint from a billion-voxel grid should terminate without mutation");
    }

    auto extremeIntrinsics = packet;
    extremeIntrinsics.calibration.fx = 1.0e-300;
    extremeIntrinsics.calibration.fy = 1.0e-300;
    aether::reconstruction::SparseTsdfConfig footprint;
    footprint.volume = planeConfig();
    footprint.blockResolution = 4;
    footprint.maximumBlocks = 1'000;
    auto guarded = aether::reconstruction::SparseTsdfVolume::create(footprint);
    expect(guarded.has_value(), "footprint-guard sparse volume should be created");
    if (guarded) {
        const auto integrated =
            guarded->integrate(extremeIntrinsics, observation.pose, observation.depth);
        expect(!integrated.has_value() &&
                   integrated.error().code == aether::ErrorCode::resourceExhausted &&
                   guarded->statistics().allocatedBlocks == 0 &&
                   guarded->statistics().integratedFrames == 0,
               "non-finite ray footprints should fail before allocation or fusion");
    }

    auto nonFinitePrincipalPoint = packet;
    nonFinitePrincipalPoint.calibration.cx = std::numeric_limits<double>::quiet_NaN();
    auto invalidObservation = observation;
    invalidObservation.pose.confidence = std::numeric_limits<double>::quiet_NaN();
    if (guarded) {
        expect(!guarded->integrate(nonFinitePrincipalPoint, observation.pose, observation.depth)
                       .has_value() &&
                   !guarded->integrate(packet, invalidObservation.pose, observation.depth)
                        .has_value() &&
                   guarded->statistics().allocatedBlocks == 0,
               "non-finite calibration and pose confidence should fail before projection");
    }

    auto nonFiniteExtent = footprint;
    nonFiniteExtent.volume.originMetres[0] = std::numeric_limits<double>::max();
    nonFiniteExtent.volume.voxelSizeMetres = std::numeric_limits<double>::max();
    nonFiniteExtent.volume.truncationDistanceMetres = std::numeric_limits<double>::max();
    expect(!aether::reconstruction::SparseTsdfVolume::create(nonFiniteExtent).has_value(),
           "a logical volume whose world extent overflows should be rejected at creation");
}

} // namespace

int main(int argc, char** argv) noexcept {
    try {
        const auto destinations = outputPaths(argc, argv);
        testDenseParityAndDeterminism();
        testIncrementalHaloMeshing();
        testRoomScaleLogicalGridAndTransactionalBudgets();
        testHostileConfiguration();
        if (failures == 0 && destinations.sparse)
            writeEvidence(*destinations.sparse);
        if (failures == 0 && destinations.incremental)
            writeIncrementalEvidence(*destinations.incremental);
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }
    if (failures == 0)
        std::cout << "Sparse TSDF tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
