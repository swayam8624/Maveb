#pragma once

#include <aether/core/Error.hpp>
#include <aether/scene/Transform.hpp>

#include <cstddef>
#include <filesystem>
#include <vector>

namespace aether::scene {

struct CameraKeyframe final {
    double seconds{};
    Transform transform;
    float verticalFieldOfViewRadians{1.0471975512F};
    float exposureEv{};
};

class CameraPath final {
  public:
    /// Input: versioned JSON camera path and an explicit keyframe allocation bound.
    /// Output: strictly time-ordered, finite camera keyframes.
    [[nodiscard]] static Result<CameraPath> load(const std::filesystem::path& path,
                                                 std::size_t maximumKeyframes = 1'000'000);

    /// Input: validated path and destination.
    /// Output: deterministic, atomically replaced JSON using `[x,y,z,w]` quaternions.
    [[nodiscard]] Result<void> save(const std::filesystem::path& path) const;

    /// Input: seconds on the path timeline.
    /// Output: clamped linear position/FOV/exposure and shortest-path quaternion interpolation.
    [[nodiscard]] Result<CameraKeyframe> sample(double seconds) const;

    [[nodiscard]] const std::vector<CameraKeyframe>& keyframes() const noexcept {
        return keyframes_;
    }
    [[nodiscard]] double duration() const noexcept;
    [[nodiscard]] Result<void> validate() const;

    std::vector<CameraKeyframe>& editableKeyframes() noexcept {
        return keyframes_;
    }

  private:
    std::vector<CameraKeyframe> keyframes_;
};

} // namespace aether::scene
