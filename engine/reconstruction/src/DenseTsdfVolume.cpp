#include <aether/reconstruction/DenseTsdfVolume.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <numbers>
#include <unordered_map>
#include <utility>

#include <simd/simd.h>

namespace aether::reconstruction {
namespace {

constexpr std::size_t maximumVoxelCount = 64ULL * 1024ULL * 1024ULL;
constexpr std::size_t maximumBoundsSamples = 4ULL * 1024ULL * 1024ULL;

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

double dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}

Vec3 normalized(const Vec3& value) {
    const auto length = std::sqrt(dot(value, value));
    return length > 1.0e-12 ? scale(value, 1.0 / length) : Vec3{0.0, 0.0, 1.0};
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
    const auto norm = std::sqrt(pose.orientation[0] * pose.orientation[0] +
                                pose.orientation[1] * pose.orientation[1] +
                                pose.orientation[2] * pose.orientation[2] +
                                pose.orientation[3] * pose.orientation[3]);
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

std::array<float, 3> readColor(const capture::CapturePacket& packet,
                               std::uint32_t x, std::uint32_t y) {
    if (packet.colorPlanes.empty() || !packet.colorPlanes.front().valid())
        return {};
    const auto& plane = packet.colorPlanes.front();
    if (packet.calibration.width == 0 || packet.calibration.height == 0)
        return {};
    const auto colorX = std::min<std::uint32_t>(
        plane.width - 1,
        static_cast<std::uint32_t>(
            static_cast<std::uint64_t>(x) * plane.width / packet.calibration.width));
    const auto colorY = std::min<std::uint32_t>(
        plane.height - 1,
        static_cast<std::uint32_t>(
            static_cast<std::uint64_t>(y) * plane.height / packet.calibration.height));
    const auto* row = plane.buffer.data +
                      static_cast<std::size_t>(colorY) * plane.rowStrideBytes;
    switch (plane.format) {
    case capture::PixelFormat::gray8: {
        const auto value =
            static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) / 255.0F;
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
        const auto* chromaRow = chroma.buffer.data +
                                static_cast<std::size_t>(chromaY) *
                                    chroma.rowStrideBytes;
        const auto* chromaPixel = chromaRow + static_cast<std::size_t>(chromaX) * 2;
        const float luminance = std::clamp(
            (static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) - 16.0F) /
                219.0F,
            0.0F, 1.0F);
        const float cb =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[0])) - 128.0F) /
            224.0F;
        const float cr =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[1])) - 128.0F) /
            224.0F;
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

constexpr std::array<std::array<int, 3>, 8> cornerOffsets{{
    {{0, 0, 0}}, {{1, 0, 0}}, {{1, 1, 0}}, {{0, 1, 0}},
    {{0, 0, 1}}, {{1, 0, 1}}, {{1, 1, 1}}, {{0, 1, 1}},
}};

constexpr std::array<std::array<int, 2>, 12> edgeCorners{{
    {{0, 1}}, {{1, 2}}, {{2, 3}}, {{3, 0}},
    {{4, 5}}, {{5, 6}}, {{6, 7}}, {{7, 4}},
    {{0, 4}}, {{1, 5}}, {{2, 6}}, {{3, 7}},
}};

struct Face final {
    std::array<int, 4> corners;
    std::array<int, 4> edges;
};

constexpr std::array<Face, 6> faces{{
    {{{0, 1, 2, 3}}, {{0, 1, 2, 3}}},
    {{{4, 5, 6, 7}}, {{4, 5, 6, 7}}},
    {{{0, 1, 5, 4}}, {{0, 9, 4, 8}}},
    {{{1, 2, 6, 5}}, {{1, 10, 5, 9}}},
    {{{2, 3, 7, 6}}, {{2, 11, 6, 10}}},
    {{{3, 0, 4, 7}}, {{3, 8, 7, 11}}},
}};

} // namespace

DenseTsdfBoundsEstimator::DenseTsdfBoundsEstimator(DenseTsdfBoundsConfig config)
    : config_(std::move(config)) {}

Result<DenseTsdfBoundsEstimator> DenseTsdfBoundsEstimator::create(DenseTsdfBoundsConfig config) {
    if (config.pixelStride == 0 || config.maximumAxisVoxels < 2 ||
        !std::isfinite(config.minimumVoxelSizeMetres) || config.minimumVoxelSizeMetres <= 0.0 ||
        !std::isfinite(config.paddingMetres) || config.paddingMetres < 0.0 ||
        !std::isfinite(config.lowerQuantile) || !std::isfinite(config.upperQuantile) ||
        config.lowerQuantile < 0.0 || config.upperQuantile > 1.0 ||
        config.lowerQuantile >= config.upperQuantile)
        return fail(ErrorCode::invalidArgument, "TSDF automatic-bounds configuration is invalid");
    return DenseTsdfBoundsEstimator(std::move(config));
}

Result<void> DenseTsdfBoundsEstimator::observe(const capture::CapturePacket& packet,
                                               const PoseEstimate& pose,
                                               const DepthObservation& depth) {
    if (!finitePose(pose.cameraToWorld) || !pose.metricScale || !depth.depthMetres.valid() ||
        depth.depthMetres.format != capture::PixelFormat::depthFloat32Metres ||
        depth.depthMetres.width != packet.calibration.width ||
        depth.depthMetres.height != packet.calibration.height || packet.calibration.fx <= 0.0 ||
        packet.calibration.fy <= 0.0 || !std::isfinite(depth.scaleMetresPerUnit) ||
        depth.scaleMetresPerUnit <= 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Automatic bounds require calibrated metric depth and pose");
    if (depth.confidence && (!depth.confidence->valid() ||
                             depth.confidence->format != capture::PixelFormat::confidenceUInt8 ||
                             depth.confidence->width != depth.depthMetres.width ||
                             depth.confidence->height != depth.depthMetres.height))
        return fail(ErrorCode::invalidArgument,
                    "Automatic-bounds depth confidence plane is invalid");

    const auto stride = config_.pixelStride;
    for (std::uint32_t y = stride / 2; y < depth.depthMetres.height; y += stride) {
        for (std::uint32_t x = stride / 2; x < depth.depthMetres.width; x += stride) {
            if (coordinates_[0].size() >= maximumBoundsSamples)
                return fail(ErrorCode::resourceExhausted,
                            "Automatic-bounds sample budget exceeded");
            const auto confidence = confidenceWeight(depth.confidence, x, y);
            if (confidence < depth.confidenceFloor)
                continue;
            const auto metres =
                static_cast<double>(readDepth(depth.depthMetres, x, y)) * depth.scaleMetresPerUnit;
            if (!std::isfinite(metres) || metres < 0.05 || metres > 20.0)
                continue;
            const Vec3 camera{
                (static_cast<double>(x) - packet.calibration.cx) * metres / packet.calibration.fx,
                (static_cast<double>(y) - packet.calibration.cy) * metres / packet.calibration.fy,
                metres,
            };
            const auto world =
                add(pose.cameraToWorld.translation, rotate(pose.cameraToWorld.orientation, camera));
            for (std::size_t axis = 0; axis < 3; ++axis)
                coordinates_[axis].push_back(world[axis]);
        }
    }
    return {};
}

Result<DenseTsdfBoundsResult> DenseTsdfBoundsEstimator::estimate() const {
    if (coordinates_[0].size() < 8)
        return fail(ErrorCode::invalidArgument,
                    "Too few valid metric depth samples to estimate TSDF bounds");

    DenseTsdfBoundsResult result;
    result.sampledPoints = coordinates_[0].size();
    std::array<double, 3> paddedMaximum{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        auto values = coordinates_[axis];
        std::sort(values.begin(), values.end());
        const auto quantileIndex = [&](double quantile) {
            return std::min(
                values.size() - 1,
                static_cast<std::size_t>(quantile * static_cast<double>(values.size() - 1)));
        };
        result.observedMinimumMetres[axis] = values[quantileIndex(config_.lowerQuantile)];
        result.observedMaximumMetres[axis] = values[quantileIndex(config_.upperQuantile)];
        result.volume.originMetres[axis] =
            result.observedMinimumMetres[axis] - config_.paddingMetres;
        paddedMaximum[axis] = result.observedMaximumMetres[axis] + config_.paddingMetres;
    }

    double voxelSize = config_.minimumVoxelSizeMetres;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto span = paddedMaximum[axis] - result.volume.originMetres[axis];
        if (!std::isfinite(span) || span <= 0.0)
            return fail(ErrorCode::invalidArgument,
                        "Observed TSDF bounds are degenerate or non-finite");
        voxelSize = std::max(voxelSize, span / static_cast<double>(config_.maximumAxisVoxels - 1));
    }
    result.volume.voxelSizeMetres = voxelSize;
    result.volume.truncationDistanceMetres = std::max(4.0 * voxelSize, 0.04);
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto span = paddedMaximum[axis] - result.volume.originMetres[axis];
        result.volume.dimensions[axis] =
            static_cast<std::uint32_t>(std::clamp(std::ceil(span / voxelSize) + 1.0, 2.0,
                                                  static_cast<double>(config_.maximumAxisVoxels)));
    }
    return result;
}

DenseTsdfVolume::DenseTsdfVolume(DenseTsdfConfig config) : config_(std::move(config)) {
    const auto count = static_cast<std::size_t>(config_.dimensions[0]) *
                       config_.dimensions[1] * config_.dimensions[2];
    voxels_.resize(count);
}

Result<DenseTsdfVolume> DenseTsdfVolume::create(DenseTsdfConfig config) {
    if (config.dimensions[0] < 2 || config.dimensions[1] < 2 || config.dimensions[2] < 2)
        return fail(ErrorCode::invalidArgument, "TSDF dimensions must each be at least two");
    const auto xy = static_cast<std::size_t>(config.dimensions[0]) * config.dimensions[1];
    if (xy / config.dimensions[0] != config.dimensions[1] ||
        config.dimensions[2] > maximumVoxelCount / xy)
        return fail(ErrorCode::resourceExhausted, "TSDF voxel count exceeds its budget");
    if (!std::isfinite(config.voxelSizeMetres) || config.voxelSizeMetres <= 0.0 ||
        !std::isfinite(config.truncationDistanceMetres) ||
        config.truncationDistanceMetres < config.voxelSizeMetres ||
        !std::isfinite(config.minimumDepthMetres) || config.minimumDepthMetres < 0.0 ||
        !std::isfinite(config.maximumDepthMetres) ||
        config.maximumDepthMetres <= config.minimumDepthMetres ||
        !std::isfinite(config.maximumWeight) || config.maximumWeight <= 0.0)
        return fail(ErrorCode::invalidArgument, "TSDF configuration is invalid");
    for (const auto value : config.originMetres)
        if (!std::isfinite(value))
            return fail(ErrorCode::invalidArgument, "TSDF origin is non-finite");
    return DenseTsdfVolume(std::move(config));
}

std::size_t DenseTsdfVolume::index(std::uint32_t x, std::uint32_t y,
                                   std::uint32_t z) const noexcept {
    return (static_cast<std::size_t>(z) * config_.dimensions[1] + y) *
               config_.dimensions[0] +
           x;
}

Result<void> DenseTsdfVolume::integrate(const capture::CapturePacket& packet,
                                        const PoseEstimate& pose,
                                        const DepthObservation& depth) {
    if (!finitePose(pose.cameraToWorld) || pose.confidence < 0.0 || pose.confidence > 1.0)
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
    if (depth.confidence &&
        (!depth.confidence->valid() ||
         depth.confidence->format != capture::PixelFormat::confidenceUInt8 ||
         depth.confidence->width != depth.depthMetres.width ||
         depth.confidence->height != depth.depthMetres.height))
        return fail(ErrorCode::invalidArgument, "Depth confidence plane is invalid");

    const auto& cameraToWorld = pose.cameraToWorld;
    const std::array<double, 4> worldToCamera{
        cameraToWorld.orientation[0],
        -cameraToWorld.orientation[1],
        -cameraToWorld.orientation[2],
        -cameraToWorld.orientation[3],
    };
    std::size_t updates = 0;
    for (std::uint32_t z = 0; z < config_.dimensions[2]; ++z) {
        for (std::uint32_t y = 0; y < config_.dimensions[1]; ++y) {
            for (std::uint32_t x = 0; x < config_.dimensions[0]; ++x) {
                const Vec3 world{
                    config_.originMetres[0] + static_cast<double>(x) * config_.voxelSizeMetres,
                    config_.originMetres[1] + static_cast<double>(y) * config_.voxelSizeMetres,
                    config_.originMetres[2] + static_cast<double>(z) * config_.voxelSizeMetres,
                };
                const auto camera =
                    rotate(worldToCamera, subtract(world, cameraToWorld.translation));
                if (camera[2] <= config_.minimumDepthMetres)
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
                    observedDepth < config_.minimumDepthMetres ||
                    observedDepth > config_.maximumDepthMetres)
                    continue;
                const auto confidence = confidenceWeight(depth.confidence, px, py);
                if (confidence < depth.confidenceFloor)
                    continue;
                const auto signedDistance = observedDepth - camera[2];
                if (signedDistance < -config_.truncationDistanceMetres)
                    continue;
                const auto normalizedDistance =
                    std::clamp(signedDistance / config_.truncationDistanceMetres, -1.0, 1.0);
                const auto sampleWeight = confidence * pose.confidence;
                if (sampleWeight <= 0.0)
                    continue;

                auto& voxel = voxels_[index(x, y, z)];
                const auto oldWeight = static_cast<double>(voxel.weight);
                const auto combinedWeight =
                    std::min(config_.maximumWeight, oldWeight + sampleWeight);
                const auto contribution = std::min(sampleWeight, combinedWeight);
                const auto retained = combinedWeight - contribution;
                voxel.distance = static_cast<float>(
                    (static_cast<double>(voxel.distance) * retained +
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

Result<mesh::MeshAsset> DenseTsdfVolume::extractMesh() const {
    mesh::MeshAsset asset;
    asset.name = "tsdf-isosurface";
    mesh::MeshPrimitive primitive;
    primitive.name = "tsdf-surface";

    std::unordered_map<std::uint64_t, std::uint32_t> edgeVertices;
    const auto position = [&](std::uint32_t x, std::uint32_t y, std::uint32_t z) -> Vec3 {
        return {config_.originMetres[0] + static_cast<double>(x) * config_.voxelSizeMetres,
                config_.originMetres[1] + static_cast<double>(y) * config_.voxelSizeMetres,
                config_.originMetres[2] + static_cast<double>(z) * config_.voxelSizeMetres};
    };
    const auto gradient = [&](std::uint32_t x, std::uint32_t y, std::uint32_t z) -> Vec3 {
        const auto lowX = x == 0 ? x : x - 1;
        const auto highX = std::min(x + 1, config_.dimensions[0] - 1);
        const auto lowY = y == 0 ? y : y - 1;
        const auto highY = std::min(y + 1, config_.dimensions[1] - 1);
        const auto lowZ = z == 0 ? z : z - 1;
        const auto highZ = std::min(z + 1, config_.dimensions[2] - 1);
        return normalized({
            static_cast<double>(voxels_[index(highX, y, z)].distance -
                                voxels_[index(lowX, y, z)].distance),
            static_cast<double>(voxels_[index(x, highY, z)].distance -
                                voxels_[index(x, lowY, z)].distance),
            static_cast<double>(voxels_[index(x, y, highZ)].distance -
                                voxels_[index(x, y, lowZ)].distance),
        });
    };

    for (std::uint32_t z = 0; z + 1 < config_.dimensions[2]; ++z) {
        for (std::uint32_t y = 0; y + 1 < config_.dimensions[1]; ++y) {
            for (std::uint32_t x = 0; x + 1 < config_.dimensions[0]; ++x) {
                std::array<const TsdfVoxel*, 8> corners{};
                std::array<float, 8> values{};
                bool observed = true;
                int caseIndex = 0;
                for (std::size_t corner = 0; corner < corners.size(); ++corner) {
                    const auto cx = x + static_cast<std::uint32_t>(cornerOffsets[corner][0]);
                    const auto cy = y + static_cast<std::uint32_t>(cornerOffsets[corner][1]);
                    const auto cz = z + static_cast<std::uint32_t>(cornerOffsets[corner][2]);
                    corners[corner] = &voxels_[index(cx, cy, cz)];
                    values[corner] = corners[corner]->distance;
                    observed = observed && corners[corner]->weight > 0.0F;
                    if (values[corner] < 0.0F)
                        caseIndex |= 1 << corner;
                }
                if (!observed || caseIndex == 0 || caseIndex == 255)
                    continue;

                std::array<bool, 12> activeEdges{};
                std::array<std::vector<int>, 12> adjacency;
                for (std::size_t edge = 0; edge < edgeCorners.size(); ++edge) {
                    const auto a = edgeCorners[edge][0];
                    const auto b = edgeCorners[edge][1];
                    activeEdges[edge] =
                        (values[static_cast<std::size_t>(a)] < 0.0F) !=
                        (values[static_cast<std::size_t>(b)] < 0.0F);
                }
                const auto connect = [&](int a, int b) {
                    adjacency[static_cast<std::size_t>(a)].push_back(b);
                    adjacency[static_cast<std::size_t>(b)].push_back(a);
                };
                for (const auto& face : faces) {
                    std::array<int, 4> crossing{};
                    std::size_t count = 0;
                    for (const auto edge : face.edges)
                        if (activeEdges[static_cast<std::size_t>(edge)])
                            crossing[count++] = edge;
                    if (count == 2) {
                        connect(crossing[0], crossing[1]);
                    } else if (count == 4) {
                        double centre = 0.0;
                        for (const auto corner : face.corners)
                            centre += values[static_cast<std::size_t>(corner)];
                        centre *= 0.25;
                        const bool centreMatchesFirst =
                            (centre < 0.0) ==
                            (values[static_cast<std::size_t>(face.corners[0])] < 0.0F);
                        if (centreMatchesFirst) {
                            connect(face.edges[0], face.edges[1]);
                            connect(face.edges[2], face.edges[3]);
                        } else {
                            connect(face.edges[0], face.edges[3]);
                            connect(face.edges[1], face.edges[2]);
                        }
                    }
                }

                const auto vertexForEdge = [&](int edge) -> std::uint32_t {
                    const auto a = edgeCorners[static_cast<std::size_t>(edge)][0];
                    const auto b = edgeCorners[static_cast<std::size_t>(edge)][1];
                    const auto& offsetA = cornerOffsets[static_cast<std::size_t>(a)];
                    const auto& offsetB = cornerOffsets[static_cast<std::size_t>(b)];
                    const auto ax = x + static_cast<std::uint32_t>(offsetA[0]);
                    const auto ay = y + static_cast<std::uint32_t>(offsetA[1]);
                    const auto az = z + static_cast<std::uint32_t>(offsetA[2]);
                    const auto bx = x + static_cast<std::uint32_t>(offsetB[0]);
                    const auto by = y + static_cast<std::uint32_t>(offsetB[1]);
                    const auto bz = z + static_cast<std::uint32_t>(offsetB[2]);
                    const auto lowX = std::min(ax, bx);
                    const auto lowY = std::min(ay, by);
                    const auto lowZ = std::min(az, bz);
                    const std::uint64_t pointIndex =
                        (static_cast<std::uint64_t>(lowZ) * config_.dimensions[1] + lowY) *
                            config_.dimensions[0] +
                        lowX;
                    const std::uint64_t axis = ax != bx ? 0 : (ay != by ? 1 : 2);
                    const auto key = pointIndex * 3 + axis;
                    if (const auto found = edgeVertices.find(key); found != edgeVertices.end())
                        return found->second;

                    const auto cornerA = static_cast<std::size_t>(a);
                    const auto cornerB = static_cast<std::size_t>(b);
                    const auto denominator = static_cast<double>(values[cornerA]) -
                                             static_cast<double>(values[cornerB]);
                    const auto t = std::abs(denominator) > 1.0e-12
                                       ? std::clamp(static_cast<double>(values[cornerA]) /
                                                        denominator,
                                                    0.0, 1.0)
                                       : 0.5;
                    const auto pa = position(ax, ay, az);
                    const auto pb = position(bx, by, bz);
                    const auto point = add(pa, scale(subtract(pb, pa), t));
                    const auto normal = normalized(add(
                        scale(gradient(ax, ay, az), 1.0 - t),
                        scale(gradient(bx, by, bz), t)));
                    std::array<float, 3> color{};
                    for (std::size_t channel = 0; channel < 3; ++channel)
                        color[channel] = static_cast<float>(
                            static_cast<double>(corners[cornerA]->color[channel]) * (1.0 - t) +
                            static_cast<double>(corners[cornerB]->color[channel]) * t);

                    mesh::MeshVertex vertex{};
                    vertex.position = simd_make_float3(static_cast<float>(point[0]),
                                                       static_cast<float>(point[1]),
                                                       static_cast<float>(point[2]));
                    vertex.normal = simd_make_float3(static_cast<float>(normal[0]),
                                                     static_cast<float>(normal[1]),
                                                     static_cast<float>(normal[2]));
                    vertex.tangent = simd_make_float4(1.0F, 0.0F, 0.0F, 1.0F);
                    const auto result = static_cast<std::uint32_t>(primitive.vertices.size());
                    primitive.vertices.push_back(vertex);
                    primitive.vertexColors.push_back(
                        simd_make_float3(color[0], color[1], color[2]));
                    edgeVertices.emplace(key, result);
                    return result;
                };

                std::array<bool, 12> visited{};
                for (int start = 0; start < 12; ++start) {
                    if (!activeEdges[static_cast<std::size_t>(start)] ||
                        visited[static_cast<std::size_t>(start)] ||
                        adjacency[static_cast<std::size_t>(start)].size() != 2)
                        continue;
                    std::vector<int> loopEdges;
                    int previous = -1;
                    int current = start;
                    do {
                        visited[static_cast<std::size_t>(current)] = true;
                        loopEdges.push_back(current);
                        const auto& neighbours = adjacency[static_cast<std::size_t>(current)];
                        const int next = neighbours[0] == previous ? neighbours[1] : neighbours[0];
                        previous = current;
                        current = next;
                    } while (current != start && current >= 0 &&
                             !visited[static_cast<std::size_t>(current)]);
                    if (current != start || loopEdges.size() < 3)
                        continue;

                    std::vector<std::uint32_t> loop;
                    loop.reserve(loopEdges.size());
                    Vec3 centre{};
                    Vec3 centreNormal{};
                    simd_float3 centreColor{};
                    for (const auto edge : loopEdges) {
                        const auto vertexIndex = vertexForEdge(edge);
                        loop.push_back(vertexIndex);
                        const auto& vertex = primitive.vertices[vertexIndex];
                        centre = add(centre, {vertex.position.x, vertex.position.y,
                                              vertex.position.z});
                        centreNormal = add(centreNormal, {vertex.normal.x, vertex.normal.y,
                                                         vertex.normal.z});
                        centreColor += primitive.vertexColors[vertexIndex];
                    }
                    centre = scale(centre, 1.0 / static_cast<double>(loop.size()));
                    centreNormal = normalized(centreNormal);
                    centreColor /= static_cast<float>(loop.size());
                    mesh::MeshVertex centreVertex{};
                    centreVertex.position = simd_make_float3(
                        static_cast<float>(centre[0]), static_cast<float>(centre[1]),
                        static_cast<float>(centre[2]));
                    centreVertex.normal = simd_make_float3(
                        static_cast<float>(centreNormal[0]),
                        static_cast<float>(centreNormal[1]),
                        static_cast<float>(centreNormal[2]));
                    centreVertex.tangent = simd_make_float4(1.0F, 0.0F, 0.0F, 1.0F);
                    const auto centreIndex =
                        static_cast<std::uint32_t>(primitive.vertices.size());
                    primitive.vertices.push_back(centreVertex);
                    primitive.vertexColors.push_back(centreColor);

                    const auto& first = primitive.vertices[loop[0]].position;
                    const auto& second = primitive.vertices[loop[1]].position;
                    const auto windingNormal = cross(
                        {static_cast<double>(first.x - centreVertex.position.x),
                         static_cast<double>(first.y - centreVertex.position.y),
                         static_cast<double>(first.z - centreVertex.position.z)},
                        {static_cast<double>(second.x - centreVertex.position.x),
                         static_cast<double>(second.y - centreVertex.position.y),
                         static_cast<double>(second.z - centreVertex.position.z)});
                    if (dot(windingNormal, centreNormal) < 0.0)
                        std::reverse(loop.begin(), loop.end());
                    for (std::size_t index = 0; index < loop.size(); ++index) {
                        primitive.indices.push_back(centreIndex);
                        primitive.indices.push_back(loop[index]);
                        primitive.indices.push_back(loop[(index + 1) % loop.size()]);
                    }
                }
            }
        }
    }

    if (primitive.vertices.empty())
        return fail(ErrorCode::notFound, "Observed TSDF contains no zero crossing");
    primitive.materialIndex = 0;
    asset.primitives.push_back(std::move(primitive));
    mesh::SceneNode node;
    node.name = "tsdf-root";
    asset.nodes.push_back(node);
    mesh::MeshInstance instance;
    instance.name = "tsdf-instance";
    instance.primitiveIndex = 0;
    instance.nodeIndex = 0;
    asset.instances.push_back(instance);
    return asset;
}

} // namespace aether::reconstruction
