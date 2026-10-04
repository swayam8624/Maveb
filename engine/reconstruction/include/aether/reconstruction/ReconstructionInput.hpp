#pragma once

#include <aether/core/Error.hpp>

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace aether::reconstruction {

enum class ReconstructionInputKind : std::uint8_t { unorderedPhotos, video, multiCamera };
enum class MatcherStrategy : std::uint8_t { exhaustive, sequential };
enum class CameraGroupingMode : std::uint8_t { singleCamera, perFolder, perImage };

struct CameraGroup final {
    std::string id;
    std::filesystem::path relativeDirectory;
    std::string device;
    std::string lens;
    std::optional<double> focalLengthMillimetres;
    std::string calibrationId;
};

struct CameraGroupManifest final {
    std::uint32_t schemaVersion{1};
    std::vector<CameraGroup> groups;
};

/// Input: a versioned camera-group JSON file rooted at the reconstruction image directory.
/// Output: bounded device, lens, focal-length, and calibration grouping metadata.
/// Task: preserve camera identity so COLMAP does not merge incompatible intrinsics.
[[nodiscard]] Result<CameraGroupManifest>
loadCameraGroupManifest(const std::filesystem::path& path);

/// Input: declared camera groups and selected image paths relative to the image root.
/// Output: success only when every image belongs to exactly one declared parent directory.
/// Task: prevent partial, overlapping, or filename-guessed multi-camera reconstruction.
[[nodiscard]] Result<void>
validateCameraGroups(const CameraGroupManifest& manifest,
                     const std::vector<std::filesystem::path>& relativeImages);

[[nodiscard]] MatcherStrategy defaultMatcher(ReconstructionInputKind kind) noexcept;
[[nodiscard]] CameraGroupingMode defaultCameraGrouping(ReconstructionInputKind kind) noexcept;
[[nodiscard]] std::string_view toString(ReconstructionInputKind kind) noexcept;
[[nodiscard]] std::string_view toString(MatcherStrategy strategy) noexcept;
[[nodiscard]] std::string_view toString(CameraGroupingMode mode) noexcept;

} // namespace aether::reconstruction
