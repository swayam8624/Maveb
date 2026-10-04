#pragma once

#include <aether/capture/CapturePacket.hpp>
#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <cstdint>
#include <string>

namespace aether::reconstruction {

struct PoseEstimate final {
    capture::RigidPose cameraToWorld;
    double confidence{};
    std::uint32_t inlierCount{};
    double reprojectionErrorPixels{};
    bool metricScale{};
};

struct DepthObservation final {
    capture::ImagePlane depthMetres;
    const capture::ImagePlane* confidence{};
    double scaleMetresPerUnit{1.0};
    double confidenceFloor{};
    std::string providerId;
};

class IPoseProvider {
public:
    virtual ~IPoseProvider() = default;
    virtual Result<PoseEstimate> estimate(const capture::CapturePacket& packet) = 0;
};

class IDepthProvider {
public:
    virtual ~IDepthProvider() = default;
    virtual Result<DepthObservation> estimate(const capture::CapturePacket& packet,
                                              const PoseEstimate& pose) = 0;
};

class IVolumeFusion {
public:
    virtual ~IVolumeFusion() = default;
    virtual Result<void> integrate(const capture::CapturePacket& packet,
                                   const PoseEstimate& pose,
                                   const DepthObservation& depth) = 0;
};

class IMeshExtractor {
public:
    virtual ~IMeshExtractor() = default;
    virtual Result<mesh::MeshAsset> extractMesh() const = 0;
};

} // namespace aether::reconstruction
