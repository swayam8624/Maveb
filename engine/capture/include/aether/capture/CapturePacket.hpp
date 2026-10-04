#pragma once

#include <aether/capture/calibration/CameraCalibration.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace aether::capture {

enum class CaptureSourceKind {
    camera,
    recordedRgbd,
    lidar,
    estimatedRgbDepth,
    syntheticTest,
};

enum class PixelFormat {
    gray8,
    rgb8,
    bgra8,
    yuv420BiPlanarVideoRange,
    depthFloat32Metres,
    confidenceUInt8,
};

enum class ImageOrientation {
    up,
    right,
    down,
    left,
};

/// Type-erased immutable storage plus a byte view into it. The owner keeps platform buffers alive.
struct BufferView final {
    std::shared_ptr<const void> owner;
    const std::byte* data{};
    std::size_t sizeBytes{};

    [[nodiscard]] bool valid() const noexcept {
        return owner && data != nullptr && sizeBytes != 0;
    }
};

struct ImagePlane final {
    BufferView buffer;
    PixelFormat format{PixelFormat::gray8};
    std::uint32_t width{};
    std::uint32_t height{};
    std::uint32_t rowStrideBytes{};

    [[nodiscard]] bool valid() const noexcept;
};

/// Camera-to-world rigid pose. The quaternion is stored as (w, x, y, z).
struct RigidPose final {
    std::array<double, 4> orientation{1.0, 0.0, 0.0, 0.0};
    std::array<double, 3> translation{};
};

struct ExposureSample final {
    double durationSeconds{};
    double iso{};
};

struct ImuSample final {
    std::uint64_t timestampNs{};
    std::array<double, 3> accelerationMetresPerSecondSquared{};
    std::array<double, 3> angularVelocityRadiansPerSecond{};
};

/// Immutable synchronized capture unit passed between bounded pipeline stages.
struct CapturePacket final {
    std::uint64_t frameId{};
    std::string sourceId;
    CaptureSourceKind sourceKind{CaptureSourceKind::camera};
    std::uint64_t presentationTimestampNs{};
    std::uint64_t hostTimestampNs{};
    ImageOrientation orientation{ImageOrientation::up};
    bool mirrored{};
    CameraCalibration calibration;
    std::vector<ImagePlane> colorPlanes;
    std::optional<ImagePlane> depthMetres;
    std::optional<ImagePlane> depthConfidence;
    std::optional<RigidPose> cameraToWorld;
    std::optional<ExposureSample> exposure;
    std::vector<ImuSample> imuSamples;

    [[nodiscard]] bool hasMetricDepth() const noexcept;
};

/// Creates immutable storage for fixtures, decoded recordings, and CPU-produced depth.
[[nodiscard]] BufferView makeOwnedBuffer(std::vector<std::byte> bytes);

} // namespace aether::capture
