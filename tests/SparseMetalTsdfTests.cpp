#include <aether/metal/MetalPtr.hpp>
#include <aether/metal/SparseMetalTsdfVolume.hpp>
#include <aether/reconstruction/RecordedProviders.hpp>
#include <aether/reconstruction/SparseTsdfVolume.hpp>

#include <Foundation/Foundation.hpp>
#include <Metal/Metal.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numbers>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

aether::capture::CapturePacket makePlanePacket(float planeDepth = 1.0F) {
    constexpr std::uint32_t width = 48;
    constexpr std::uint32_t height = 40;
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
    packet.sourceId = "sparse-metal-plane";
    packet.sourceKind = aether::capture::CaptureSourceKind::recordedRgbd;
    packet.calibration.id = packet.sourceId;
    packet.calibration.width = width;
    packet.calibration.height = height;
    packet.calibration.fx = 48.0;
    packet.calibration.fy = 48.0;
    packet.calibration.cx = 23.5;
    packet.calibration.cy = 19.5;
    packet.colorPlanes.push_back(
        aether::capture::ImagePlane{aether::capture::makeOwnedBuffer(std::move(color)),
                                    aether::capture::PixelFormat::rgb8, width, height, width * 3});
    packet.depthMetres =
        aether::capture::ImagePlane{aether::capture::makeOwnedBuffer(std::move(depth)),
                                    aether::capture::PixelFormat::depthFloat32Metres, width, height,
                                    width * static_cast<std::uint32_t>(sizeof(float))};
    constexpr double halfAngleRadians = 5.0 * std::numbers::pi / 180.0;
    packet.cameraToWorld = aether::capture::RigidPose{
        {std::cos(halfAngleRadians), 0.0, std::sin(halfAngleRadians), 0.0}, {0.02, -0.03, 0.01}};
    return packet;
}

struct Observation final {
    aether::reconstruction::PoseEstimate pose;
    aether::reconstruction::DepthObservation depth;
};

Observation makeObservation(aether::capture::CapturePacket& packet) {
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

aether::reconstruction::SparseTsdfConfig makeConfig() {
    aether::reconstruction::SparseTsdfConfig config;
    config.volume.dimensions = {21, 21, 17};
    config.volume.originMetres = {-0.4, -0.4, 0.68};
    config.volume.voxelSizeMetres = 0.04;
    config.volume.truncationDistanceMetres = 0.08;
    config.volume.minimumDepthMetres = 0.1;
    config.volume.maximumDepthMetres = 2.0;
    config.volume.maximumWeight = 2.0;
    config.blockResolution = 4;
    config.maximumBlocks = 1'000;
    return config;
}

std::optional<aether::reconstruction::TsdfVoxel>
snapshotVoxel(const aether::metal::SparseMetalTsdfSnapshot& snapshot, std::uint32_t x,
              std::uint32_t y, std::uint32_t z) {
    const auto blockResolution = snapshot.config.blockResolution;
    const aether::reconstruction::TsdfBlockCoordinate coordinate{
        x / blockResolution, y / blockResolution, z / blockResolution};
    const auto block = std::ranges::find_if(
        snapshot.blocks, [&](const auto& candidate) { return candidate.coordinate == coordinate; });
    if (block == snapshot.blocks.end())
        return std::nullopt;
    const auto localX = x % blockResolution;
    const auto localY = y % blockResolution;
    const auto localZ = z % blockResolution;
    const auto index =
        (static_cast<std::size_t>(localZ) * blockResolution + localY) * blockResolution + localX;
    return block->voxels[index];
}

bool nearVoxel(const aether::reconstruction::TsdfVoxel& cpu,
               const aether::reconstruction::TsdfVoxel& gpu) {
    constexpr float tolerance = 2.0e-5F;
    return std::abs(cpu.distance - gpu.distance) <= tolerance &&
           std::abs(cpu.weight - gpu.weight) <= tolerance &&
           std::abs(cpu.color[0] - gpu.color[0]) <= tolerance &&
           std::abs(cpu.color[1] - gpu.color[1]) <= tolerance &&
           std::abs(cpu.color[2] - gpu.color[2]) <= tolerance &&
           cpu.observations == gpu.observations;
}

bool sameSnapshot(const aether::metal::SparseMetalTsdfSnapshot& left,
                  const aether::metal::SparseMetalTsdfSnapshot& right) {
    if (left.blocks.size() != right.blocks.size())
        return false;
    for (std::size_t block = 0; block < left.blocks.size(); ++block) {
        if (left.blocks[block].coordinate != right.blocks[block].coordinate ||
            left.blocks[block].voxels.size() != right.blocks[block].voxels.size())
            return false;
        for (std::size_t voxel = 0; voxel < left.blocks[block].voxels.size(); ++voxel)
            if (!nearVoxel(left.blocks[block].voxels[voxel], right.blocks[block].voxels[voxel]))
                return false;
    }
    return true;
}

} // namespace

int main(int argc, char** argv) { // NOLINT(bugprone-exception-escape)
    std::optional<std::filesystem::path> jsonOutput;
    if (argc == 3 && std::string_view(argv[1]) == "--json-output")
        jsonOutput = argv[2];
    else if (argc != 1) {
        std::cerr << "Usage: AetherSparseMetalTsdfTests [--json-output <path>]\n";
        return 2;
    }

    auto pool = aether::metal::adopt(NS::AutoreleasePool::alloc()->init());
    auto device = aether::metal::adopt(MTL::CreateSystemDefaultDevice());
    if (!device) {
        std::cerr << "No Metal device available\n";
        return 1;
    }
    NS::Error* libraryError = nullptr;
    auto library = aether::metal::adopt(device->newLibrary(
        NS::String::string(AETHER_TEST_SHADER_LIBRARY, NS::UTF8StringEncoding), &libraryError));
    if (!library) {
        std::cerr << "Unable to load Sparse TSDF test shader library\n";
        return 1;
    }

    auto packet = makePlanePacket();
    const auto observation = makeObservation(packet);
    const auto config = makeConfig();
    auto candidates = aether::reconstruction::SparseTsdfVolume::candidateBlocks(
        config, packet, observation.pose, observation.depth);
    auto candidatesAgain = aether::reconstruction::SparseTsdfVolume::candidateBlocks(
        config, packet, observation.pose, observation.depth);
    expect(candidates && candidatesAgain && !candidates->empty() && *candidates == *candidatesAgain,
           "shared sparse candidate selection should be stable and non-empty");
    auto invalidCandidateConfig = config;
    invalidCandidateConfig.blockResolution = 3;
    expect(!aether::reconstruction::SparseTsdfVolume::candidateBlocks(
               invalidCandidateConfig, packet, observation.pose, observation.depth),
           "shared sparse candidate selection should enforce volume configuration validation");

    auto cpu = aether::reconstruction::SparseTsdfVolume::create(config);
    auto gpu = aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(), config);
    auto deterministic =
        aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(), config);
    expect(cpu && gpu && deterministic, "CPU and Metal sparse volumes should be created");
    if (!cpu || !gpu || !deterministic)
        return 1;

    expect(cpu->integrate(packet, observation.pose, observation.depth).has_value() &&
               (*gpu)->integrate(packet, observation.pose, observation.depth).has_value() &&
               (*deterministic)->integrate(packet, observation.pose, observation.depth).has_value(),
           "CPU and Metal sparse volumes should integrate a translated and rotated plane");
    const auto firstSnapshot = (*gpu)->snapshot();
    const auto deterministicSnapshot = (*deterministic)->snapshot();
    expect(firstSnapshot && deterministicSnapshot &&
               sameSnapshot(*firstSnapshot, *deterministicSnapshot),
           "independent Metal volumes should produce deterministic snapshots");
    expect(firstSnapshot && firstSnapshot->generation == 1,
           "first immutable Metal snapshot should report generation one");

    expect(cpu->integrate(packet, observation.pose, observation.depth).has_value() &&
               (*gpu)->integrate(packet, observation.pose, observation.depth).has_value(),
           "CPU and Metal sparse volumes should preserve repeated-frame weight saturation");
    const auto finalSnapshot = (*gpu)->snapshot();
    expect(firstSnapshot && finalSnapshot && finalSnapshot->generation == 2 &&
               firstSnapshot->generation == 1,
           "later fusion should advance generation without mutating an earlier snapshot");

    std::size_t compared{};
    std::size_t mismatched{};
    if (finalSnapshot) {
        for (std::uint32_t z = 0; z < config.volume.dimensions[2]; ++z)
            for (std::uint32_t y = 0; y < config.volume.dimensions[1]; ++y)
                for (std::uint32_t x = 0; x < config.volume.dimensions[0]; ++x) {
                    const auto cpuVoxel = cpu->voxel(x, y, z);
                    const auto gpuVoxel = snapshotVoxel(*finalSnapshot, x, y, z);
                    if (cpuVoxel.has_value() != gpuVoxel.has_value()) {
                        ++mismatched;
                        continue;
                    }
                    if (!cpuVoxel)
                        continue;
                    ++compared;
                    if (!nearVoxel(*cpuVoxel, *gpuVoxel))
                        ++mismatched;
                }
    }
    expect(compared > 0 && mismatched == 0,
           "Metal snapshot voxels should agree with the CPU sparse reference");
    const auto cpuStats = cpu->statistics();
    const auto gpuStats = (*gpu)->statistics();
    expect(gpuStats.residentBlocks == cpuStats.allocatedBlocks &&
               gpuStats.observedVoxels == cpuStats.observedVoxels &&
               gpuStats.lastFrameCandidateBlocks == cpuStats.lastFrameCandidateBlocks &&
               gpuStats.lastFrameVoxelUpdates == cpuStats.lastFrameVoxelUpdates &&
               gpuStats.integratedFrames == 2 && gpuStats.generation == 2,
           "Metal sparse allocation and fusion counters should match the CPU reference");
    expect((*gpu)->dirtyBlocks() == cpu->dirtyBlocks(),
           "Metal and CPU dirty-block coordinates should match exactly");
    (*gpu)->clearDirtyBlocks();
    expect((*gpu)->dirtyBlocks().empty() && (*gpu)->statistics().dirtyBlocks == 0,
           "Metal dirty-block acknowledgement should not alter resident data");

    auto boundedConfig = config;
    boundedConfig.maximumBlocks = 1;
    auto bounded =
        aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(), boundedConfig);
    expect(bounded && !(*bounded)->integrate(packet, observation.pose, observation.depth) &&
               (*bounded)->statistics().residentBlocks == 0 &&
               (*bounded)->statistics().reservedPayloadBytes == 0 &&
               (*bounded)->statistics().generation == 0 && !(*bounded)->snapshot(),
           "resident-budget rejection should leave a Metal volume empty and unadvanced");

    aether::metal::SparseMetalTsdfLimits invalidLimits;
    invalidLimits.maximumFramePixels = 0;
    expect(!aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(), config,
                                                         invalidLimits),
           "zero Metal memory limits should be rejected at creation");

    aether::metal::SparseMetalTsdfLimits frameLimits;
    frameLimits.maximumFramePixels = 1;
    auto frameBounded = aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(),
                                                                     config, frameLimits);
    expect(frameBounded &&
               !(*frameBounded)->integrate(packet, observation.pose, observation.depth) &&
               (*frameBounded)->statistics().residentBlocks == 0 &&
               (*frameBounded)->statistics().reservedPayloadBytes == 0 &&
               (*frameBounded)->statistics().generation == 0,
           "frame-pixel rejection should leave a Metal volume empty and unadvanced");

    aether::metal::SparseMetalTsdfLimits residentLimits;
    residentLimits.maximumResidentBytes = 1;
    auto residentBounded = aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(),
                                                                        config, residentLimits);
    expect(residentBounded &&
               !(*residentBounded)->integrate(packet, observation.pose, observation.depth) &&
               (*residentBounded)->statistics().residentBlocks == 0 &&
               (*residentBounded)->statistics().reservedPayloadBytes == 0 &&
               (*residentBounded)->statistics().generation == 0,
           "resident-byte rejection should leave a Metal volume empty and unadvanced");

    aether::metal::SparseMetalTsdfLimits scratchLimits;
    scratchLimits.maximumScratchBytes = 1;
    auto scratchBounded = aether::metal::SparseMetalTsdfVolume::create(device.get(), library.get(),
                                                                       config, scratchLimits);
    expect(scratchBounded &&
               !(*scratchBounded)->integrate(packet, observation.pose, observation.depth) &&
               (*scratchBounded)->statistics().residentBlocks == 0 &&
               (*scratchBounded)->statistics().reservedPayloadBytes == 0 &&
               (*scratchBounded)->statistics().generation == 0,
           "scratch-byte rejection should leave a Metal volume empty and unadvanced");

    if (jsonOutput) {
        std::error_code error;
        std::filesystem::create_directories(jsonOutput->parent_path(), error);
        std::ofstream output(*jsonOutput, std::ios::trunc);
        output << "{\n"
               << "  \"schemaVersion\": 1,\n"
               << "  \"evidenceLevel\": \"E2-fixture\",\n"
               << "  \"backend\": \"metal-3-block-sparse-tsdf\",\n"
               << "  \"device\": \"" << device->name()->utf8String() << "\",\n"
               << "  \"parity\": {\n"
               << "    \"blockResolution\": 4,\n"
               << "    \"cameraPose\": \"translated-and-yaw-rotated\",\n"
               << "    \"repeatedFrames\": 2,\n"
               << "    \"candidateBlocks\": " << gpuStats.lastFrameCandidateBlocks << ",\n"
               << "    \"residentBlocks\": " << gpuStats.residentBlocks << ",\n"
               << "    \"observedVoxels\": " << gpuStats.observedVoxels << ",\n"
               << "    \"voxelUpdates\": " << gpuStats.lastFrameVoxelUpdates << ",\n"
               << "    \"comparedVoxels\": " << compared << ",\n"
               << "    \"mismatchedVoxels\": " << mismatched << "\n"
               << "  },\n"
               << "  \"boundedFailures\": {\n"
               << "    \"residentBlockBudget\": true,\n"
               << "    \"framePixelBudget\": true,\n"
               << "    \"residentByteBudget\": true,\n"
               << "    \"scratchByteBudget\": true\n"
               << "  },\n"
               << "  \"limitations\": [\n"
               << "    \"Synthetic fixture evidence is not real-capture E3 accuracy evidence.\",\n"
               << "    \"Synchronous fixture execution is not an R5 throughput claim.\",\n"
               << "    \"Incremental meshing, persistence, eviction, and live scheduling remain "
                  "open.\"\n"
               << "  ]\n"
               << "}\n";
        expect(!error && static_cast<bool>(output),
               "Sparse Metal evidence JSON should be written for CTest");
    }
    return failures == 0 ? 0 : 1;
}
