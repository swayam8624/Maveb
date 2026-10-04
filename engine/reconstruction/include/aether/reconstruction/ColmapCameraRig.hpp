#pragma once

#include <aether/core/Error.hpp>
#include <aether/reconstruction/SensorAlignment.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace aether::reconstruction {

struct ColmapCameraRecord final {
    std::uint64_t imageId{};
    std::uint64_t cameraId{};
    std::string imageName;
    AlignmentCameraPose cameraToWorld;
};

struct ColmapCameraRigLimits final {
    std::size_t maximumImages{10'000'000};
    std::size_t maximumLineBytes{16ULL * 1024ULL * 1024ULL};
};

/// Input: COLMAP's text-format images.txt and explicit hostile-input limits.
/// Output: unique relative image names with camera-to-world centers and (w,x,y,z) orientations.
/// Task: invert COLMAP world-to-camera poses without changing its +X-right,+Y-down,+Z-forward axes.
/// Failure: malformed alternating pose/observation lines, duplicate IDs/names, path traversal,
/// non-finite/degenerate quaternions, oversized input, or I/O failure returns a structured error.
[[nodiscard]] Result<std::vector<ColmapCameraRecord>>
loadColmapCameraRig(const std::filesystem::path& imagesText,
                    const ColmapCameraRigLimits& limits = {});

} // namespace aether::reconstruction
