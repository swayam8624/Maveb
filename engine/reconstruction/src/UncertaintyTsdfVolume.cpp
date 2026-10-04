#include <aether/reconstruction/UncertaintyTsdfVolume.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <utility>

namespace aether::reconstruction {
namespace {

using Vec3 = std::array<double, 3>;

Vec3 add(const Vec3& a, const Vec3& b) {
    return {a[0] + b[0], a[1] + b[1], a[2] + b[2]};
}

Vec3 subtract(const Vec3& a, const Vec3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

Vec3 scale(const Vec3& value, double factor) {
    return {value[0] * factor, value[1] * factor, value[2] * factor};
}

Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}

Vec3 rotate(const std::array<double, 4>& quaternion, const Vec3& value) {
    const Vec3 q{quaternion[1], quaternion[2], quaternion[3]};
    const auto uv = cross(q, value);
    const auto uuv = cross(q, uv);
    return add(value, add(scale(uv, 2.0 * quaternion[0]), scale(uuv, 2.0)));
}

bool finitePose(const capture::RigidPose& pose) {
    for (const auto value : pose.orientation)
        if (!std::isfinite(value))
            return false;
    for (const auto value : pose.translation)
        if (!std::isfinite(value))
            return false;
    const auto norm = std::sqrt(
        pose.orientation[0] * pose.orientation[0] + pose.orientation[1] * pose.orientation[1] +
        pose.orientation[2] * pose.orientation[2] + pose.orientation[3] * pose.orientation[3]);
    return std::abs(norm - 1.0) <= 1.0e-3;
}

bool validUncertaintyConfig(const MetricUncertaintyFusionConfig& config) {
    const std::array values{
        config.minimumSigmaMetres,         config.maximumSigmaMetres,
        config.depthNoiseFloorMetres,      config.depthNoiseQuadraticMetresPerMetreSquared,
        config.sensorConfidencePenalty,    config.poseTranslationFloorMetres,
        config.poseTranslationScaleMetres, config.referenceSigmaMetres,
        config.minimumPrecisionWeight,     config.maximumPrecisionWeight,
    };
    if (!std::ranges::all_of(values, [](double value) { return std::isfinite(value); }))
        return false;
    return config.minimumSigmaMetres > 0.0 &&
           config.maximumSigmaMetres >= config.minimumSigmaMetres &&
           config.depthNoiseFloorMetres >= 0.0 &&
           config.depthNoiseQuadraticMetresPerMetreSquared >= 0.0 &&
           config.sensorConfidencePenalty >= 0.0 && config.poseTranslationFloorMetres >= 0.0 &&
           config.poseTranslationScaleMetres >= 0.0 && config.referenceSigmaMetres > 0.0 &&
           config.minimumPrecisionWeight > 0.0 &&
           config.maximumPrecisionWeight >= config.minimumPrecisionWeight;
}

float readDepth(const capture::ImagePlane& plane, std::uint32_t x, std::uint32_t y) {
    float value{};
    const auto* row = plane.buffer.data + static_cast<std::size_t>(y) * plane.rowStrideBytes;
    std::memcpy(&value, row + static_cast<std::size_t>(x) * sizeof(float), sizeof(float));
    return value;
}

double confidenceWeight(const capture::ImagePlane* plane, std::uint32_t x, std::uint32_t y) {
    if (!plane)
        return 1.0;
    const auto* row = plane->buffer.data + static_cast<std::size_t>(y) * plane->rowStrideBytes;
    return static_cast<double>(std::to_integer<std::uint8_t>(row[x])) / 255.0;
}

std::array<float, 3> readColor(const capture::CapturePacket& packet, std::uint32_t x,
                               std::uint32_t y) {
    if (packet.colorPlanes.empty() || !packet.colorPlanes.front().valid())
        return {};
    const auto& plane = packet.colorPlanes.front();
    if (packet.calibration.width == 0 || packet.calibration.height == 0)
        return {};
    const auto colorX = std::min<std::uint32_t>(
        plane.width - 1, static_cast<std::uint32_t>(static_cast<std::uint64_t>(x) * plane.width /
                                                    packet.calibration.width));
    const auto colorY = std::min<std::uint32_t>(
        plane.height - 1, static_cast<std::uint32_t>(static_cast<std::uint64_t>(y) * plane.height /
                                                     packet.calibration.height));
    const auto* row = plane.buffer.data + static_cast<std::size_t>(colorY) * plane.rowStrideBytes;
    switch (plane.format) {
    case capture::PixelFormat::gray8: {
        const auto value = static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) / 255.0F;
        return {value, value, value};
    }
    case capture::PixelFormat::rgb8: {
        const auto* pixel = row + static_cast<std::size_t>(colorX) * 3;
        return {static_cast<float>(std::to_integer<std::uint8_t>(pixel[0])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[1])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[2])) / 255.0F};
    }
    case capture::PixelFormat::bgra8: {
        const auto* pixel = row + static_cast<std::size_t>(colorX) * 4;
        return {static_cast<float>(std::to_integer<std::uint8_t>(pixel[2])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[1])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[0])) / 255.0F};
    }
    case capture::PixelFormat::yuv420BiPlanarVideoRange: {
        if (packet.colorPlanes.size() != 2 || !packet.colorPlanes[1].valid())
            return {};
        const auto& chroma = packet.colorPlanes[1];
        const auto chromaX = std::min<std::uint32_t>(chroma.width - 1, colorX / 2);
        const auto chromaY = std::min<std::uint32_t>(chroma.height - 1, colorY / 2);
        const auto* chromaRow =
            chroma.buffer.data + static_cast<std::size_t>(chromaY) * chroma.rowStrideBytes;
        const auto* chromaPixel = chromaRow + static_cast<std::size_t>(chromaX) * 2;
        const float luminance = std::clamp(
            (static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) - 16.0F) / 219.0F, 0.0F,
            1.0F);
        const float cb =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[0])) - 128.0F) / 224.0F;
        const float cr =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[1])) - 128.0F) / 224.0F;
        return {
            std::clamp(luminance + 1.5748F * cr, 0.0F, 1.0F),
            std::clamp(luminance - 0.1873F * cb - 0.4681F * cr, 0.0F, 1.0F),
            std::clamp(luminance + 1.8556F * cb, 0.0F, 1.0F),
        };
    }
    default:
        return {};
    }
}

} // namespace

Result<TsdfFusionWeight> predictTsdfFusionWeight(double observedDepthMetres,
                                                 double sensorConfidence, const PoseEstimate& pose,
                                                 double focalLengthPixels,
                                                 TsdfFusionWeighting weighting,
                                                 const MetricUncertaintyFusionConfig& config) {
    if (!std::isfinite(observedDepthMetres) || observedDepthMetres <= 0.0 ||
        !std::isfinite(sensorConfidence) || sensorConfidence < 0.0 || sensorConfidence > 1.0 ||
        !std::isfinite(pose.confidence) || pose.confidence < 0.0 || pose.confidence > 1.0 ||
        !std::isfinite(pose.reprojectionErrorPixels) || pose.reprojectionErrorPixels < 0.0 ||
        !std::isfinite(focalLengthPixels) || focalLengthPixels <= 0.0 ||
        !validUncertaintyConfig(config))
        return fail(ErrorCode::invalidArgument, "TSDF fusion-weight inputs are invalid");

    TsdfFusionWeight result;
    result.sensorConfidence = sensorConfidence;
    switch (weighting) {
    case TsdfFusionWeighting::uniform:
        result.precisionWeight = 1.0;
        result.sampleWeight = pose.confidence;
        return result;
    case TsdfFusionWeighting::naiveConfidence:
        result.precisionWeight = sensorConfidence;
        result.sampleWeight = sensorConfidence * pose.confidence;
        return result;
    case TsdfFusionWeighting::calibratedInverseVariance:
        break;
    default:
        return fail(ErrorCode::invalidArgument, "Unknown TSDF fusion weighting mode");
    }

    const auto baseSensorSigma =
        config.depthNoiseFloorMetres +
        config.depthNoiseQuadraticMetresPerMetreSquared * observedDepthMetres * observedDepthMetres;
    const auto sensorSigma =
        baseSensorSigma * (1.0 + config.sensorConfidencePenalty * (1.0 - sensorConfidence));
    const auto poseTranslationSigma = config.poseTranslationFloorMetres +
                                      config.poseTranslationScaleMetres * (1.0 - pose.confidence);
    const auto reprojectionSigma =
        observedDepthMetres * pose.reprojectionErrorPixels / focalLengthPixels;
    const auto variance = sensorSigma * sensorSigma + poseTranslationSigma * poseTranslationSigma +
                          reprojectionSigma * reprojectionSigma;
    result.predictedSigmaMetres =
        std::clamp(std::sqrt(variance), config.minimumSigmaMetres, config.maximumSigmaMetres);
    const auto rawPrecision = (config.referenceSigmaMetres / result.predictedSigmaMetres) *
                              (config.referenceSigmaMetres / result.predictedSigmaMetres);
    result.precisionWeight =
        std::clamp(rawPrecision, config.minimumPrecisionWeight, config.maximumPrecisionWeight);
    result.sampleWeight = pose.confidence <= 0.0 ? 0.0 : result.precisionWeight;
    return result;
}

UncertaintyTsdfVolume::UncertaintyTsdfVolume(UncertaintyTsdfConfig config) : config_(config) {
    const auto& dimensions = config_.volume.dimensions;
    const auto count = static_cast<std::size_t>(dimensions[0]) * dimensions[1] * dimensions[2];
    voxels_.resize(count);
}

Result<UncertaintyTsdfVolume> UncertaintyTsdfVolume::create(UncertaintyTsdfConfig config) {
    {
        auto validatedVolume = DenseTsdfVolume::create(config.volume);
        if (!validatedVolume)
            return std::unexpected(validatedVolume.error());
    }
    if (!validUncertaintyConfig(config.uncertainty))
        return fail(ErrorCode::invalidArgument,
                    "Metric uncertainty fusion configuration is invalid");
    return UncertaintyTsdfVolume(config);
}

std::size_t UncertaintyTsdfVolume::index(std::uint32_t x, std::uint32_t y,
                                         std::uint32_t z) const noexcept {
    return (static_cast<std::size_t>(z) * config_.volume.dimensions[1] + y) *
               config_.volume.dimensions[0] +
           x;
}

Result<void> UncertaintyTsdfVolume::integrate(const capture::CapturePacket& packet,
                                              const PoseEstimate& pose,
                                              const DepthObservation& depth) {
    if (!finitePose(pose.cameraToWorld) || !std::isfinite(pose.confidence) ||
        pose.confidence < 0.0 || pose.confidence > 1.0 ||
        !std::isfinite(pose.reprojectionErrorPixels) || pose.reprojectionErrorPixels < 0.0)
        return fail(ErrorCode::invalidArgument, "Pose estimate is invalid");
    if (!pose.metricScale)
        return fail(ErrorCode::invalidArgument, "TSDF integration requires metric-scale poses");
    if (!depth.depthMetres.valid() ||
        depth.depthMetres.format != capture::PixelFormat::depthFloat32Metres)
        return fail(ErrorCode::invalidArgument, "Depth observation is not valid float32 metres");
    if (depth.depthMetres.width != packet.calibration.width ||
        depth.depthMetres.height != packet.calibration.height ||
        !std::isfinite(depth.scaleMetresPerUnit) || depth.scaleMetresPerUnit <= 0.0 ||
        packet.calibration.fx <= 0.0 || packet.calibration.fy <= 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Depth dimensions, scale, or camera intrinsics are invalid");
    if (depth.confidence && (!depth.confidence->valid() ||
                             depth.confidence->format != capture::PixelFormat::confidenceUInt8 ||
                             depth.confidence->width != depth.depthMetres.width ||
                             depth.confidence->height != depth.depthMetres.height))
        return fail(ErrorCode::invalidArgument, "Depth confidence plane is invalid");

    const auto& volume = config_.volume;
    const auto& cameraToWorld = pose.cameraToWorld;
    const std::array<double, 4> worldToCamera{
        cameraToWorld.orientation[0],
        -cameraToWorld.orientation[1],
        -cameraToWorld.orientation[2],
        -cameraToWorld.orientation[3],
    };
    const auto focalLengthPixels = std::sqrt(packet.calibration.fx * packet.calibration.fy);
    std::size_t updates = 0;
    for (std::uint32_t z = 0; z < volume.dimensions[2]; ++z) {
        for (std::uint32_t y = 0; y < volume.dimensions[1]; ++y) {
            for (std::uint32_t x = 0; x < volume.dimensions[0]; ++x) {
                const Vec3 world{
                    volume.originMetres[0] + static_cast<double>(x) * volume.voxelSizeMetres,
                    volume.originMetres[1] + static_cast<double>(y) * volume.voxelSizeMetres,
                    volume.originMetres[2] + static_cast<double>(z) * volume.voxelSizeMetres,
                };
                const auto camera =
                    rotate(worldToCamera, subtract(world, cameraToWorld.translation));
                if (camera[2] <= volume.minimumDepthMetres)
                    continue;
                const auto projectedX =
                    packet.calibration.fx * camera[0] / camera[2] + packet.calibration.cx;
                const auto projectedY =
                    packet.calibration.fy * camera[1] / camera[2] + packet.calibration.cy;
                const auto pixelX = static_cast<long>(std::llround(projectedX));
                const auto pixelY = static_cast<long>(std::llround(projectedY));
                if (pixelX < 0 || pixelY < 0 ||
                    pixelX >= static_cast<long>(depth.depthMetres.width) ||
                    pixelY >= static_cast<long>(depth.depthMetres.height))
                    continue;
                const auto px = static_cast<std::uint32_t>(pixelX);
                const auto py = static_cast<std::uint32_t>(pixelY);
                const auto observedDepth =
                    static_cast<double>(readDepth(depth.depthMetres, px, py)) *
                    depth.scaleMetresPerUnit;
                if (!std::isfinite(observedDepth) || observedDepth < volume.minimumDepthMetres ||
                    observedDepth > volume.maximumDepthMetres)
                    continue;
                const auto confidence = confidenceWeight(depth.confidence, px, py);
                if (confidence < depth.confidenceFloor)
                    continue;
                const auto signedDistance = observedDepth - camera[2];
                if (signedDistance < -volume.truncationDistanceMetres)
                    continue;
                const auto normalizedDistance =
                    std::clamp(signedDistance / volume.truncationDistanceMetres, -1.0, 1.0);
                auto fusionWeight =
                    predictTsdfFusionWeight(observedDepth, confidence, pose, focalLengthPixels,
                                            config_.weighting, config_.uncertainty);
                if (!fusionWeight)
                    return std::unexpected(fusionWeight.error());
                const auto sampleWeight = fusionWeight->sampleWeight;
                if (sampleWeight <= 0.0)
                    continue;

                auto& voxel = voxels_[index(x, y, z)];
                const auto oldWeight = static_cast<double>(voxel.weight);
                const auto combinedWeight =
                    std::min(volume.maximumWeight, oldWeight + sampleWeight);
                const auto contribution = std::min(sampleWeight, combinedWeight);
                const auto retained = combinedWeight - contribution;
                voxel.distance =
                    static_cast<float>((static_cast<double>(voxel.distance) * retained +
                                        normalizedDistance * contribution) /
                                       combinedWeight);
                const auto color = readColor(packet, px, py);
                for (std::size_t channel = 0; channel < 3; ++channel)
                    voxel.color[channel] =
                        static_cast<float>((static_cast<double>(voxel.color[channel]) * retained +
                                            static_cast<double>(color[channel]) * contribution) /
                                           combinedWeight);
                voxel.weight = static_cast<float>(combinedWeight);
                ++voxel.observations;
                ++updates;
            }
        }
    }
    if (updates == 0)
        return fail(ErrorCode::invalidArgument,
                    "Depth frame did not observe any voxel in the configured volume",
                    std::to_string(packet.frameId));
    ++integratedFrames_;
    return {};
}

Result<mesh::MeshAsset> UncertaintyTsdfVolume::extractMesh() const {
    auto scalarField = DenseTsdfVolume::fromScalarField(config_.volume, voxels_);
    if (!scalarField)
        return std::unexpected(scalarField.error());
    return scalarField->extractMesh();
}

} // namespace aether::reconstruction
