#include <aether/capture/CapturePacket.hpp>
#include <aether/reconstruction/DenseTsdfVolume.hpp>
#include <aether/reconstruction/UncertaintyTsdfVolume.hpp>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string_view>
#include <vector>

namespace {

int failures = 0;

void expect(bool condition, std::string_view message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

constexpr std::uint32_t width = 8;
constexpr std::uint32_t height = 8;

struct FrameFixture final {
    aether::capture::CapturePacket packet;
    aether::reconstruction::DepthObservation observation;
};

FrameFixture makeFrame(std::uint64_t frameId, float depthMetres, std::uint8_t confidence) {
    std::vector<std::byte> depth(static_cast<std::size_t>(width) * height * sizeof(float));
    for (std::size_t index = 0; index < static_cast<std::size_t>(width) * height; ++index)
        std::memcpy(depth.data() + index * sizeof(float), &depthMetres, sizeof(float));
    std::vector<std::byte> confidenceBytes(static_cast<std::size_t>(width) * height,
                                           static_cast<std::byte>(confidence));

    aether::capture::CapturePacket packet;
    packet.frameId = frameId;
    packet.sourceId = "u3-tsdf-oracle";
    packet.sourceKind = aether::capture::CaptureSourceKind::syntheticTest;
    packet.calibration.id = packet.sourceId;
    packet.calibration.width = width;
    packet.calibration.height = height;
    packet.calibration.fx = 100.0;
    packet.calibration.fy = 100.0;
    packet.calibration.cx = 3.5;
    packet.calibration.cy = 3.5;
    packet.depthMetres = aether::capture::ImagePlane{
        aether::capture::makeOwnedBuffer(std::move(depth)),
        aether::capture::PixelFormat::depthFloat32Metres,
        width,
        height,
        width * static_cast<std::uint32_t>(sizeof(float)),
    };
    packet.depthConfidence = aether::capture::ImagePlane{
        aether::capture::makeOwnedBuffer(std::move(confidenceBytes)),
        aether::capture::PixelFormat::confidenceUInt8,
        width,
        height,
        width,
    };
    packet.cameraToWorld = aether::capture::RigidPose{};

    auto observation = aether::reconstruction::DepthObservation{
        *packet.depthMetres,
        &*packet.depthConfidence,
        1.0,
        0.0,
        "u3-oracle",
    };
    return FrameFixture{std::move(packet), observation};
}

aether::reconstruction::DenseTsdfConfig volumeConfig() {
    aether::reconstruction::DenseTsdfConfig config;
    config.dimensions = {3, 3, 13};
    config.originMetres = {-0.04, -0.04, 0.8};
    config.voxelSizeMetres = 0.04;
    config.truncationDistanceMetres = 0.20;
    config.minimumDepthMetres = 0.10;
    config.maximumDepthMetres = 2.0;
    config.maximumWeight = 100.0;
    return config;
}

aether::reconstruction::MetricUncertaintyFusionConfig frozenU1bConfig() {
    aether::reconstruction::MetricUncertaintyFusionConfig config;
    config.minimumSigmaMetres = 0.001;
    config.maximumSigmaMetres = 0.25;
    config.depthNoiseFloorMetres = 0.010634156727771725;
    config.depthNoiseQuadraticMetresPerMetreSquared = 0.004398048551220112;
    config.sensorConfidencePenalty = 5.990146384791633;
    config.poseTranslationFloorMetres = 0.001;
    config.poseTranslationScaleMetres = 0.02;
    config.referenceSigmaMetres = 0.01;
    config.minimumPrecisionWeight = 0.01;
    config.maximumPrecisionWeight = 1.0;
    return config;
}

aether::reconstruction::PoseEstimate oraclePose() {
    return aether::reconstruction::PoseEstimate{
        aether::capture::RigidPose{},
        1.0,
        0,
        0.0,
        true,
    };
}

std::size_t centreVoxelIndex(const aether::reconstruction::DenseTsdfConfig& config) {
    constexpr std::uint32_t x = 1;
    constexpr std::uint32_t y = 1;
    constexpr std::uint32_t z = 6;
    return (static_cast<std::size_t>(z) * config.dimensions[1] + y) * config.dimensions[0] + x;
}

void testFrozenWeightOrdering() {
    const auto pose = oraclePose();
    const auto config = frozenU1bConfig();
    auto high = aether::reconstruction::predictTsdfFusionWeight(
        1.0, 1.0, pose, 100.0,
        aether::reconstruction::TsdfFusionWeighting::calibratedInverseVariance, config);
    auto medium = aether::reconstruction::predictTsdfFusionWeight(
        1.2, 128.0 / 255.0, pose, 100.0,
        aether::reconstruction::TsdfFusionWeighting::calibratedInverseVariance, config);
    auto low = aether::reconstruction::predictTsdfFusionWeight(
        1.2, 0.0, pose, 100.0,
        aether::reconstruction::TsdfFusionWeighting::calibratedInverseVariance, config);

    expect(high.has_value() && medium.has_value() && low.has_value(),
           "Frozen U1b weights are valid for ARKit confidence levels");
    if (!high || !medium || !low)
        return;
    expect(high->predictedSigmaMetres < medium->predictedSigmaMetres &&
               medium->predictedSigmaMetres < low->predictedSigmaMetres,
           "Frozen U1b sigma increases as confidence falls");
    expect(high->sampleWeight > medium->sampleWeight && medium->sampleWeight >= low->sampleWeight,
           "Inverse-variance fusion downweights lower-confidence depth");
    expect(low->sampleWeight >= config.minimumPrecisionWeight,
           "Low-confidence depth remains bounded rather than being silently discarded");
}

void testNaiveModeMatchesReferenceDenseTsdf() {
    const auto config = volumeConfig();
    auto reference = aether::reconstruction::DenseTsdfVolume::create(config);
    aether::reconstruction::UncertaintyTsdfConfig researchConfig;
    researchConfig.volume = config;
    researchConfig.weighting = aether::reconstruction::TsdfFusionWeighting::naiveConfidence;
    auto research = aether::reconstruction::UncertaintyTsdfVolume::create(researchConfig);
    expect(reference.has_value() && research.has_value(),
           "Reference and U3 dense volumes accept identical configuration");
    if (!reference || !research)
        return;

    auto reliable = makeFrame(1, 1.0F, 255);
    auto conflict = makeFrame(2, 1.2F, 128);
    const auto pose = oraclePose();
    expect(reference->integrate(reliable.packet, pose, reliable.observation).has_value() &&
               research->integrate(reliable.packet, pose, reliable.observation).has_value() &&
               reference->integrate(conflict.packet, pose, conflict.observation).has_value() &&
               research->integrate(conflict.packet, pose, conflict.observation).has_value(),
           "Reference and U3 naive paths integrate the same oracle frames");

    const auto& baseline = reference->voxels();
    const auto& candidate = research->voxels();
    expect(baseline.size() == candidate.size(), "Naive U3 voxel count matches the reference path");
    if (baseline.size() != candidate.size())
        return;
    for (std::size_t index = 0; index < baseline.size(); ++index) {
        expect(std::abs(static_cast<double>(baseline[index].distance) -
                        static_cast<double>(candidate[index].distance)) <= 1.0e-6,
               "Naive U3 TSDF distance matches the existing dense baseline");
        expect(std::abs(static_cast<double>(baseline[index].weight) -
                        static_cast<double>(candidate[index].weight)) <= 1.0e-6,
               "Naive U3 TSDF weight matches the existing dense baseline");
        expect(baseline[index].observations == candidate[index].observations,
               "Naive U3 observation counts match the existing dense baseline");
    }
}

void testCalibratedFusionRejectsConflictingLowConfidenceDepth() {
    const auto denseConfig = volumeConfig();
    const auto pose = oraclePose();
    auto reliable = makeFrame(1, 1.0F, 255);
    auto conflict = makeFrame(2, 1.2F, 128);

    const auto makeVolume = [&](aether::reconstruction::TsdfFusionWeighting weighting) {
        aether::reconstruction::UncertaintyTsdfConfig config;
        config.volume = denseConfig;
        config.weighting = weighting;
        config.uncertainty = frozenU1bConfig();
        return aether::reconstruction::UncertaintyTsdfVolume::create(config);
    };

    auto target = makeVolume(aether::reconstruction::TsdfFusionWeighting::uniform);
    auto uniform = makeVolume(aether::reconstruction::TsdfFusionWeighting::uniform);
    auto naive = makeVolume(aether::reconstruction::TsdfFusionWeighting::naiveConfidence);
    auto calibrated = makeVolume(
        aether::reconstruction::TsdfFusionWeighting::calibratedInverseVariance);
    expect(target.has_value() && uniform.has_value() && naive.has_value() && calibrated.has_value(),
           "All U3 oracle weighting modes create successfully");
    if (!target || !uniform || !naive || !calibrated)
        return;

    expect(target->integrate(reliable.packet, pose, reliable.observation).has_value(),
           "Reliable-only target integrates");
    for (auto* volume : {&*uniform, &*naive, &*calibrated}) {
        expect(volume->integrate(reliable.packet, pose, reliable.observation).has_value() &&
                   volume->integrate(conflict.packet, pose, conflict.observation).has_value(),
               "Two-frame U3 oracle integration succeeds");
    }

    const auto centre = centreVoxelIndex(denseConfig);
    const auto targetDistance = static_cast<double>(target->voxels()[centre].distance);
    const auto uniformDistance = static_cast<double>(uniform->voxels()[centre].distance);
    const auto naiveDistance = static_cast<double>(naive->voxels()[centre].distance);
    const auto calibratedDistance = static_cast<double>(calibrated->voxels()[centre].distance);
    const auto uniformError = std::abs(uniformDistance - targetDistance);
    const auto naiveError = std::abs(naiveDistance - targetDistance);
    const auto calibratedError = std::abs(calibratedDistance - targetDistance);

    expect(calibratedError < naiveError && naiveError < uniformError,
           "Frozen inverse-variance weighting is closest to the reliable oracle surface");
    expect(calibratedDistance < 0.0 && naiveDistance > 0.0 && uniformDistance > naiveDistance,
           "U3 oracle exposes the expected weighting separation at the conflict voxel");
}

} // namespace

int main() {
    testFrozenWeightOrdering();
    testNaiveModeMatchesReferenceDenseTsdf();
    testCalibratedFusionRejectsConflictingLowConfidenceDepth();
    if (failures != 0) {
        std::cerr << failures << " uncertainty TSDF checks failed\n";
        return 1;
    }
    std::cout << "U3 dense CPU TSDF oracle checks passed\n";
    return 0;
}
