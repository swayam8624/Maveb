#pragma once

#include <aether/scene/Transform.hpp>

#include <array>
#include <cstddef>

namespace aether::scene {

enum class CameraMove : std::size_t { forward, backward, left, right, up, down, count };

class CameraController final {
  public:
    void setMoving(CameraMove direction, bool moving) noexcept;
    void addLookDelta(float horizontalPixels, float verticalPixels) noexcept;
    void addDolly(float amount) noexcept;
    void update(double deltaSeconds) noexcept;
    void clearMovement() noexcept;

    [[nodiscard]] Transform transform() const noexcept;
    [[nodiscard]] simd_float3 position() const noexcept {
        return position_;
    }
    [[nodiscard]] float yaw() const noexcept {
        return yaw_;
    }
    [[nodiscard]] float pitch() const noexcept {
        return pitch_;
    }

    void setPosition(simd_float3 position) noexcept {
        position_ = position;
    }
    void setOrientation(float yaw, float pitch) noexcept {
        yaw_ = yaw;
        pitch_ = pitch;
    }
    void setMovementSpeed(float metersPerSecond) noexcept;

  private:
    std::array<bool, static_cast<std::size_t>(CameraMove::count)> moving_{};
    simd_float3 position_{0.0F, 0.0F, 2.5F};
    float yaw_{};
    float pitch_{};
    float movementSpeed_{3.0F};
};

} // namespace aether::scene
