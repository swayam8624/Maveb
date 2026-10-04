#include <aether/reconstruction/SparseTsdfVolume.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <set>
#include <string>
#include <utility>

namespace aether::reconstruction {
namespace {

using Vec3 = std::array<double, 3>;
using SignedBlock = std::array<std::int64_t, 3>;

Vec3 add(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 subtract(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 scale(const Vec3& value, double factor) {
    return {value[0] * factor, value[1] * factor, value[2] * factor};
}

Vec3 rotate(const std::array<double, 4>& quaternion, const Vec3& value) {
    const Vec3 vector{quaternion[1], quaternion[2], quaternion[3]};
    const Vec3 first{vector[1] * value[2] - vector[2] * value[1],
                     vector[2] * value[0] - vector[0] * value[2],
                     vector[0] * value[1] - vector[1] * value[0]};
    const Vec3 second{vector[1] * first[2] - vector[2] * first[1],
                      vector[2] * first[0] - vector[0] * first[2],
                      vector[0] * first[1] - vector[1] * first[0]};
    return add(value, add(scale(first, 2.0 * quaternion[0]), scale(second, 2.0)));
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
        return {std::clamp(luminance + 1.5748F * cr, 0.0F, 1.0F),
                std::clamp(luminance - 0.1873F * cb - 0.4681F * cr, 0.0F, 1.0F),
                std::clamp(luminance + 1.8556F * cb, 0.0F, 1.0F)};
    }
    default:
        return {};
    }
}

std::array<std::uint32_t, 3> blockCounts(const SparseTsdfConfig& config) {
    std::array<std::uint32_t, 3> result{};
    for (std::size_t axis = 0; axis < 3; ++axis)
        result[axis] =
            static_cast<std::uint32_t>((static_cast<std::uint64_t>(config.volume.dimensions[axis]) +
                                        config.blockResolution - 1) /
                                       config.blockResolution);
    return result;
}

Result<void> addRayBlocks(const SparseTsdfConfig& config, const Vec3& startWorld,
                          const Vec3& endWorld, std::uint32_t inflation,
                          std::set<TsdfBlockCoordinate>& candidates) {
    const double blockMetres = config.volume.voxelSizeMetres * config.blockResolution;
    Vec3 start{};
    Vec3 end{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        start[axis] = (startWorld[axis] - config.volume.originMetres[axis]) / blockMetres;
        end[axis] = (endWorld[axis] - config.volume.originMetres[axis]) / blockMetres;
    }
    const auto counts = blockCounts(config);
    const auto segment = subtract(end, start);
    double minimumParameter = 0.0;
    double maximumParameter = 1.0;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (std::abs(segment[axis]) <= 1.0e-15) {
            if (start[axis] < 0.0 || start[axis] >= static_cast<double>(counts[axis]))
                return {};
            continue;
        }
        double first = -start[axis] / segment[axis];
        double second = (static_cast<double>(counts[axis]) - start[axis]) / segment[axis];
        if (first > second)
            std::swap(first, second);
        minimumParameter = std::max(minimumParameter, first);
        maximumParameter = std::min(maximumParameter, second);
        if (minimumParameter > maximumParameter)
            return {};
    }
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto upper = std::nextafter(static_cast<double>(counts[axis]), 0.0);
        end[axis] = std::clamp(start[axis] + segment[axis] * maximumParameter, 0.0, upper);
        start[axis] = std::clamp(start[axis] + segment[axis] * minimumParameter, 0.0, upper);
    }
    SignedBlock current{static_cast<std::int64_t>(std::floor(start[0])),
                        static_cast<std::int64_t>(std::floor(start[1])),
                        static_cast<std::int64_t>(std::floor(start[2]))};
    const SignedBlock last{static_cast<std::int64_t>(std::floor(end[0])),
                           static_cast<std::int64_t>(std::floor(end[1])),
                           static_cast<std::int64_t>(std::floor(end[2]))};
    const Vec3 direction{subtract(end, start)};
    std::array<std::int64_t, 3> step{};
    Vec3 delta{std::numeric_limits<double>::infinity(), std::numeric_limits<double>::infinity(),
               std::numeric_limits<double>::infinity()};
    Vec3 maximum = delta;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (direction[axis] > 0.0) {
            step[axis] = 1;
            delta[axis] = 1.0 / direction[axis];
            maximum[axis] = (std::floor(start[axis]) + 1.0 - start[axis]) * delta[axis];
        } else if (direction[axis] < 0.0) {
            step[axis] = -1;
            delta[axis] = -1.0 / direction[axis];
            maximum[axis] = (start[axis] - std::floor(start[axis])) * delta[axis];
        }
    }
    const auto insertInflated = [&]() -> Result<void> {
        const auto radius = static_cast<std::int64_t>(inflation);
        const SignedBlock lower{std::max<std::int64_t>(0, current[0] - radius),
                                std::max<std::int64_t>(0, current[1] - radius),
                                std::max<std::int64_t>(0, current[2] - radius)};
        const SignedBlock upper{
            std::min<std::int64_t>(static_cast<std::int64_t>(counts[0]) - 1, current[0] + radius),
            std::min<std::int64_t>(static_cast<std::int64_t>(counts[1]) - 1, current[1] + radius),
            std::min<std::int64_t>(static_cast<std::int64_t>(counts[2]) - 1, current[2] + radius)};
        for (std::int64_t z = lower[2]; z <= upper[2]; ++z)
            for (std::int64_t y = lower[1]; y <= upper[1]; ++y)
                for (std::int64_t x = lower[0]; x <= upper[0]; ++x) {
                    candidates.insert({static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y),
                                       static_cast<std::uint32_t>(z)});
                    if (candidates.size() > config.maximumCandidateBlocksPerFrame)
                        return fail(ErrorCode::resourceExhausted,
                                    "Sparse TSDF frame exceeds its candidate-block budget");
                }
        return {};
    };
    const auto maximumSteps = static_cast<std::uint64_t>(std::abs(last[0] - current[0])) +
                              static_cast<std::uint64_t>(std::abs(last[1] - current[1])) +
                              static_cast<std::uint64_t>(std::abs(last[2] - current[2])) + 4;
    for (std::uint64_t iteration = 0; iteration < maximumSteps; ++iteration) {
        if (auto inserted = insertInflated(); !inserted)
            return inserted;
        if (current == last)
            return {};
        double next = std::numeric_limits<double>::infinity();
        for (std::size_t axis = 0; axis < 3; ++axis)
            if (current[axis] != last[axis])
                next = std::min(next, maximum[axis]);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            if (current[axis] != last[axis] && maximum[axis] <= next + 1.0e-12) {
                current[axis] += step[axis];
                maximum[axis] += delta[axis];
            }
        }
    }
    return fail(ErrorCode::internal, "Sparse TSDF ray traversal exceeded its deterministic bound");
}

Result<void> validateObservation(const capture::CapturePacket& packet, const PoseEstimate& pose,
                                 const DepthObservation& depth) {
    if (!finitePose(pose.cameraToWorld) || !std::isfinite(pose.confidence) ||
        pose.confidence < 0.0 || pose.confidence > 1.0)
        return fail(ErrorCode::invalidArgument, "Pose estimate is invalid");
    if (!pose.metricScale)
        return fail(ErrorCode::invalidArgument, "TSDF integration requires metric-scale poses");
    if (!depth.depthMetres.valid() ||
        depth.depthMetres.format != capture::PixelFormat::depthFloat32Metres)
        return fail(ErrorCode::invalidArgument, "Depth observation is not valid float32 metres");
    if (depth.depthMetres.width != packet.calibration.width ||
        depth.depthMetres.height != packet.calibration.height ||
        !std::isfinite(depth.scaleMetresPerUnit) || depth.scaleMetresPerUnit <= 0.0 ||
        !std::isfinite(depth.confidenceFloor) || depth.confidenceFloor < 0.0 ||
        depth.confidenceFloor > 1.0 || !std::isfinite(packet.calibration.fx) ||
        !std::isfinite(packet.calibration.fy) || !std::isfinite(packet.calibration.cx) ||
        !std::isfinite(packet.calibration.cy) || packet.calibration.fx <= 0.0 ||
        packet.calibration.fy <= 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Depth dimensions, scale, or camera intrinsics are invalid");
    if (depth.confidence && (!depth.confidence->valid() ||
                             depth.confidence->format != capture::PixelFormat::confidenceUInt8 ||
                             depth.confidence->width != depth.depthMetres.width ||
                             depth.confidence->height != depth.depthMetres.height))
        return fail(ErrorCode::invalidArgument, "Depth confidence plane is invalid");
    return {};
}

} // namespace

SparseTsdfVolume::SparseTsdfVolume(SparseTsdfConfig config) : config_(config) {}

Result<SparseTsdfVolume> SparseTsdfVolume::create(SparseTsdfConfig config) {
    if (config.volume.dimensions[0] < 2 || config.volume.dimensions[1] < 2 ||
        config.volume.dimensions[2] < 2 || config.blockResolution < 2 ||
        config.blockResolution > 32 ||
        (config.blockResolution & (config.blockResolution - 1)) != 0 || config.maximumBlocks == 0 ||
        config.maximumCandidateBlocksPerFrame == 0 || config.maximumExtractionVoxels == 0 ||
        config.maximumExtractionVoxels > 64ULL * 1024ULL * 1024ULL)
        return fail(ErrorCode::invalidArgument, "Sparse TSDF dimensions or budgets are invalid");
    if (!std::isfinite(config.volume.voxelSizeMetres) || config.volume.voxelSizeMetres <= 0.0 ||
        !std::isfinite(config.volume.truncationDistanceMetres) ||
        config.volume.truncationDistanceMetres < config.volume.voxelSizeMetres ||
        !std::isfinite(config.volume.minimumDepthMetres) ||
        config.volume.minimumDepthMetres < 0.0 ||
        !std::isfinite(config.volume.maximumDepthMetres) ||
        config.volume.maximumDepthMetres <= config.volume.minimumDepthMetres ||
        !std::isfinite(config.volume.maximumWeight) || config.volume.maximumWeight <= 0.0)
        return fail(ErrorCode::invalidArgument, "Sparse TSDF fusion parameters are invalid");
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto maximum =
            config.volume.originMetres[axis] +
            static_cast<double>(config.volume.dimensions[axis] - 1) * config.volume.voxelSizeMetres;
        if (!std::isfinite(config.volume.originMetres[axis]) || !std::isfinite(maximum))
            return fail(ErrorCode::invalidArgument,
                        "Sparse TSDF logical world extent is non-finite");
    }
    const auto voxelsPerBlock = static_cast<std::size_t>(config.blockResolution) *
                                config.blockResolution * config.blockResolution;
    if (config.maximumBlocks > std::numeric_limits<std::size_t>::max() / voxelsPerBlock ||
        config.maximumBlocks * voxelsPerBlock > 256ULL * 1024ULL * 1024ULL)
        return fail(ErrorCode::resourceExhausted,
                    "Sparse TSDF resident voxel budget exceeds 256 million samples");
    return SparseTsdfVolume(config);
}

std::size_t SparseTsdfVolume::blockVoxelCount() const noexcept {
    return static_cast<std::size_t>(config_.blockResolution) * config_.blockResolution *
           config_.blockResolution;
}

std::size_t SparseTsdfVolume::localIndex(std::uint32_t x, std::uint32_t y,
                                         std::uint32_t z) const noexcept {
    return (static_cast<std::size_t>(z) * config_.blockResolution + y) * config_.blockResolution +
           x;
}

Result<void> SparseTsdfVolume::integrate(const capture::CapturePacket& packet,
                                         const PoseEstimate& pose, const DepthObservation& depth) {
    auto selected = candidateBlocks(config_, packet, pose, depth);
    if (!selected)
        return std::unexpected(selected.error());
    const std::set<TsdfBlockCoordinate> candidates(selected->begin(), selected->end());
    std::size_t potentialNewBlocks{};
    for (const auto& coordinate : candidates)
        if (!blocks_.contains(coordinate))
            ++potentialNewBlocks;
    if (potentialNewBlocks > config_.maximumBlocks - blocks_.size())
        return fail(ErrorCode::resourceExhausted,
                    "Sparse TSDF candidate set exceeds its resident block budget");

    const auto& cameraToWorld = pose.cameraToWorld;
    const std::array<double, 4> worldToCamera{
        cameraToWorld.orientation[0], -cameraToWorld.orientation[1], -cameraToWorld.orientation[2],
        -cameraToWorld.orientation[3]};
    std::map<TsdfBlockCoordinate, Block> updatedBlocks;
    std::size_t updates{};
    for (const auto& coordinate : candidates) {
        Block block(blockVoxelCount());
        if (const auto existing = blocks_.find(coordinate); existing != blocks_.end())
            block = existing->second;
        std::size_t blockUpdates{};
        for (std::uint32_t localZ = 0; localZ < config_.blockResolution; ++localZ) {
            for (std::uint32_t localY = 0; localY < config_.blockResolution; ++localY) {
                for (std::uint32_t localX = 0; localX < config_.blockResolution; ++localX) {
                    const std::uint64_t x =
                        static_cast<std::uint64_t>(coordinate.x) * config_.blockResolution + localX;
                    const std::uint64_t y =
                        static_cast<std::uint64_t>(coordinate.y) * config_.blockResolution + localY;
                    const std::uint64_t z =
                        static_cast<std::uint64_t>(coordinate.z) * config_.blockResolution + localZ;
                    if (x >= config_.volume.dimensions[0] || y >= config_.volume.dimensions[1] ||
                        z >= config_.volume.dimensions[2])
                        continue;
                    const Vec3 world{config_.volume.originMetres[0] +
                                         static_cast<double>(x) * config_.volume.voxelSizeMetres,
                                     config_.volume.originMetres[1] +
                                         static_cast<double>(y) * config_.volume.voxelSizeMetres,
                                     config_.volume.originMetres[2] +
                                         static_cast<double>(z) * config_.volume.voxelSizeMetres};
                    const auto camera =
                        rotate(worldToCamera, subtract(world, cameraToWorld.translation));
                    if (camera[2] <= config_.volume.minimumDepthMetres)
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
                    if (!std::isfinite(observedDepth) ||
                        observedDepth < config_.volume.minimumDepthMetres ||
                        observedDepth > config_.volume.maximumDepthMetres)
                        continue;
                    const auto confidence = confidenceWeight(depth.confidence, px, py);
                    if (confidence < depth.confidenceFloor)
                        continue;
                    const auto signedDistance = observedDepth - camera[2];
                    if (signedDistance < -config_.volume.truncationDistanceMetres)
                        continue;
                    const auto normalizedDistance = std::clamp(
                        signedDistance / config_.volume.truncationDistanceMetres, -1.0, 1.0);
                    const auto sampleWeight = confidence * pose.confidence;
                    if (sampleWeight <= 0.0)
                        continue;
                    auto& voxel = block[localIndex(localX, localY, localZ)];
                    const auto oldWeight = static_cast<double>(voxel.weight);
                    const auto combinedWeight =
                        std::min(config_.volume.maximumWeight, oldWeight + sampleWeight);
                    const auto contribution = std::min(sampleWeight, combinedWeight);
                    const auto retained = combinedWeight - contribution;
                    voxel.distance =
                        static_cast<float>((static_cast<double>(voxel.distance) * retained +
                                            normalizedDistance * contribution) /
                                           combinedWeight);
                    const auto color = readColor(packet, px, py);
                    for (std::size_t channel = 0; channel < 3; ++channel)
                        voxel.color[channel] = static_cast<float>(
                            (static_cast<double>(voxel.color[channel]) * retained +
                             static_cast<double>(color[channel]) * contribution) /
                            combinedWeight);
                    voxel.weight = static_cast<float>(combinedWeight);
                    ++voxel.observations;
                    ++blockUpdates;
                    ++updates;
                }
            }
        }
        if (blockUpdates > 0)
            updatedBlocks.emplace(coordinate, std::move(block));
    }
    if (updates == 0)
        return fail(ErrorCode::invalidArgument,
                    "Depth frame did not observe any voxel in the configured sparse volume",
                    std::to_string(packet.frameId));
    std::size_t newBlocks{};
    for (const auto& [coordinate, block] : updatedBlocks) {
        static_cast<void>(block);
        if (!blocks_.contains(coordinate))
            ++newBlocks;
    }
    if (newBlocks > config_.maximumBlocks - blocks_.size())
        return fail(ErrorCode::resourceExhausted,
                    "Sparse TSDF integration exceeds its resident block budget");

    std::size_t observedDelta{};
    for (auto& [coordinate, block] : updatedBlocks) {
        const auto existing = blocks_.find(coordinate);
        for (std::size_t index = 0; index < block.size(); ++index)
            if (block[index].weight > 0.0F &&
                (existing == blocks_.end() || existing->second[index].weight <= 0.0F))
                ++observedDelta;
        if (existing == blocks_.end())
            blocks_.emplace(coordinate, std::move(block));
        else
            existing->second = std::move(block);
        dirtyBlocks_.insert(coordinate);
    }
    observedVoxels_ += observedDelta;
    ++integratedFrames_;
    ++generation_;
    lastFrameCandidateBlocks_ = candidates.size();
    lastFrameVoxelUpdates_ = updates;
    return {};
}

Result<std::vector<TsdfBlockCoordinate>>
SparseTsdfVolume::candidateBlocks(const SparseTsdfConfig& config,
                                  const capture::CapturePacket& packet, const PoseEstimate& pose,
                                  const DepthObservation& depth) {
    if (auto validated = create(config); !validated)
        return std::unexpected(validated.error());
    if (auto valid = validateObservation(packet, pose, depth); !valid)
        return std::unexpected(valid.error());
    std::set<TsdfBlockCoordinate> candidates;
    const auto& cameraToWorld = pose.cameraToWorld;
    for (std::uint32_t y = 0; y < depth.depthMetres.height; ++y) {
        for (std::uint32_t x = 0; x < depth.depthMetres.width; ++x) {
            const auto observedDepth =
                static_cast<double>(readDepth(depth.depthMetres, x, y)) * depth.scaleMetresPerUnit;
            const auto confidence = confidenceWeight(depth.confidence, x, y);
            if (!std::isfinite(observedDepth) || observedDepth < config.volume.minimumDepthMetres ||
                observedDepth > config.volume.maximumDepthMetres ||
                confidence < depth.confidenceFloor || confidence * pose.confidence <= 0.0)
                continue;
            const double farDepth = observedDepth + config.volume.truncationDistanceMetres;
            const auto cameraPoint = [&](double cameraDepth) -> Vec3 {
                return {(static_cast<double>(x) - packet.calibration.cx) * cameraDepth /
                            packet.calibration.fx,
                        (static_cast<double>(y) - packet.calibration.cy) * cameraDepth /
                            packet.calibration.fy,
                        cameraDepth};
            };
            const auto toWorld = [&](const Vec3& camera) {
                return add(cameraToWorld.translation, rotate(cameraToWorld.orientation, camera));
            };
            const double footprint =
                farDepth * 0.5 *
                std::sqrt(1.0 / (packet.calibration.fx * packet.calibration.fx) +
                          1.0 / (packet.calibration.fy * packet.calibration.fy));
            const double blockMetres = config.volume.voxelSizeMetres * config.blockResolution;
            const double inflationValue = std::ceil(footprint / blockMetres) + 1.0;
            const auto counts = blockCounts(config);
            const auto maximumCount = std::max({counts[0], counts[1], counts[2]});
            if (!std::isfinite(inflationValue) || inflationValue > maximumCount)
                return fail(ErrorCode::resourceExhausted,
                            "Sparse TSDF ray footprint exceeds the logical block grid");
            const auto inflation = static_cast<std::uint32_t>(inflationValue);
            auto traversed =
                addRayBlocks(config, toWorld(cameraPoint(config.volume.minimumDepthMetres)),
                             toWorld(cameraPoint(farDepth)), inflation, candidates);
            if (!traversed)
                return std::unexpected(traversed.error());
        }
    }
    if (candidates.empty())
        return fail(ErrorCode::invalidArgument,
                    "Depth frame does not intersect the configured sparse volume",
                    std::to_string(packet.frameId));

    return std::vector<TsdfBlockCoordinate>(candidates.begin(), candidates.end());
}

Result<mesh::MeshAsset> SparseTsdfVolume::extractMesh() const {
    if (blocks_.empty() || observedVoxels_ == 0)
        return fail(ErrorCode::notFound, "Sparse TSDF contains no observed voxels");
    TsdfBlockCoordinate minimum = blocks_.begin()->first;
    TsdfBlockCoordinate maximum = blocks_.begin()->first;
    for (const auto& [coordinate, block] : blocks_) {
        static_cast<void>(block);
        minimum.x = std::min(minimum.x, coordinate.x);
        minimum.y = std::min(minimum.y, coordinate.y);
        minimum.z = std::min(minimum.z, coordinate.z);
        maximum.x = std::max(maximum.x, coordinate.x);
        maximum.y = std::max(maximum.y, coordinate.y);
        maximum.z = std::max(maximum.z, coordinate.z);
    }
    const std::array<std::uint64_t, 3> first{
        static_cast<std::uint64_t>(minimum.x) * config_.blockResolution,
        static_cast<std::uint64_t>(minimum.y) * config_.blockResolution,
        static_cast<std::uint64_t>(minimum.z) * config_.blockResolution};
    const std::array<std::uint64_t, 3> last{
        std::min<std::uint64_t>((static_cast<std::uint64_t>(maximum.x) + 1) *
                                    config_.blockResolution,
                                config_.volume.dimensions[0]),
        std::min<std::uint64_t>((static_cast<std::uint64_t>(maximum.y) + 1) *
                                    config_.blockResolution,
                                config_.volume.dimensions[1]),
        std::min<std::uint64_t>((static_cast<std::uint64_t>(maximum.z) + 1) *
                                    config_.blockResolution,
                                config_.volume.dimensions[2])};
    std::array<std::uint32_t, 3> dimensions{};
    std::size_t count = 1;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto span = last[axis] - first[axis];
        if (span < 2 || span > std::numeric_limits<std::uint32_t>::max() ||
            span > config_.maximumExtractionVoxels / count)
            return fail(ErrorCode::resourceExhausted,
                        "Sparse TSDF active span exceeds its dense extraction budget");
        dimensions[axis] = static_cast<std::uint32_t>(span);
        count *= static_cast<std::size_t>(span);
    }
    std::vector<TsdfVoxel> voxels(count);
    const auto snapshotIndex = [&](std::uint64_t x, std::uint64_t y, std::uint64_t z) {
        return (static_cast<std::size_t>(z - first[2]) * dimensions[1] +
                static_cast<std::size_t>(y - first[1])) *
                   dimensions[0] +
               static_cast<std::size_t>(x - first[0]);
    };
    for (const auto& [coordinate, block] : blocks_) {
        for (std::uint32_t z = 0; z < config_.blockResolution; ++z)
            for (std::uint32_t y = 0; y < config_.blockResolution; ++y)
                for (std::uint32_t x = 0; x < config_.blockResolution; ++x) {
                    const std::uint64_t globalX =
                        static_cast<std::uint64_t>(coordinate.x) * config_.blockResolution + x;
                    const std::uint64_t globalY =
                        static_cast<std::uint64_t>(coordinate.y) * config_.blockResolution + y;
                    const std::uint64_t globalZ =
                        static_cast<std::uint64_t>(coordinate.z) * config_.blockResolution + z;
                    if (globalX >= last[0] || globalY >= last[1] || globalZ >= last[2])
                        continue;
                    voxels[snapshotIndex(globalX, globalY, globalZ)] = block[localIndex(x, y, z)];
                }
    }
    auto snapshotConfig = config_.volume;
    snapshotConfig.dimensions = dimensions;
    for (std::size_t axis = 0; axis < 3; ++axis)
        snapshotConfig.originMetres[axis] +=
            static_cast<double>(first[axis]) * snapshotConfig.voxelSizeMetres;
    auto dense = DenseTsdfVolume::fromScalarField(snapshotConfig, voxels);
    if (!dense)
        return std::unexpected(dense.error());
    return dense->extractMesh();
}

SparseTsdfStatistics SparseTsdfVolume::statistics() const noexcept {
    const auto allocatedVoxels = blocks_.size() * blockVoxelCount();
    return {.allocatedBlocks = blocks_.size(),
            .allocatedVoxels = allocatedVoxels,
            .observedVoxels = observedVoxels_,
            .voxelPayloadBytes = allocatedVoxels * sizeof(TsdfVoxel),
            .integratedFrames = integratedFrames_,
            .lastFrameCandidateBlocks = lastFrameCandidateBlocks_,
            .lastFrameVoxelUpdates = lastFrameVoxelUpdates_,
            .dirtyBlocks = dirtyBlocks_.size(),
            .generation = generation_};
}

Result<SparseTsdfSnapshot> SparseTsdfVolume::snapshot() const {
    if (blocks_.empty())
        return fail(ErrorCode::notFound, "Sparse TSDF contains no resident blocks");
    SparseTsdfSnapshot result{config_, generation_, {}};
    result.blocks.reserve(blocks_.size());
    for (const auto& [coordinate, voxels] : blocks_)
        result.blocks.push_back({coordinate, voxels});
    return result;
}

std::optional<TsdfVoxel> SparseTsdfVolume::voxel(std::uint32_t x, std::uint32_t y,
                                                 std::uint32_t z) const noexcept {
    if (x >= config_.volume.dimensions[0] || y >= config_.volume.dimensions[1] ||
        z >= config_.volume.dimensions[2])
        return std::nullopt;
    const TsdfBlockCoordinate coordinate{x / config_.blockResolution, y / config_.blockResolution,
                                         z / config_.blockResolution};
    const auto block = blocks_.find(coordinate);
    if (block == blocks_.end())
        return std::nullopt;
    return block->second[localIndex(x % config_.blockResolution, y % config_.blockResolution,
                                    z % config_.blockResolution)];
}

std::vector<TsdfBlockCoordinate> SparseTsdfVolume::dirtyBlocks() const {
    return {dirtyBlocks_.begin(), dirtyBlocks_.end()};
}

} // namespace aether::reconstruction
