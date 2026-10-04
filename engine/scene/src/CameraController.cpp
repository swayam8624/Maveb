#include <aether/scene/CameraController.hpp>

#include <algorithm>
#include <cmath>

namespace aether::scene {

void CameraController::setMoving(CameraMove direction, bool moving) noexcept {
    moving_[static_cast<std::size_t>(direction)] = moving;
}

void CameraController::addLookDelta(float horizontalPixels, float verticalPixels) noexcept {
    constexpr float radiansPerPixel = 0.003F;
    yaw_ -= horizontalPixels * radiansPerPixel;
    pitch_ = std::clamp(pitch_ - verticalPixels * radiansPerPixel, -1.553343F, 1.553343F);
}

void CameraController::addDolly(float amount) noexcept {
    const simd_quatf orientation = transform().rotation;
    const simd_float3 forward = simd_act(orientation, simd_float3{0.0F, 0.0F, -1.0F});
    position_ += forward * (amount * 0.1F);
}

void CameraController::update(double deltaSeconds) noexcept {
    if (!std::isfinite(deltaSeconds) || deltaSeconds <= 0.0) {
        return;
    }
    const simd_quatf orientation = transform().rotation;
    const simd_float3 forward = simd_act(orientation, simd_float3{0.0F, 0.0F, -1.0F});
    const simd_float3 right = simd_act(orientation, simd_float3{1.0F, 0.0F, 0.0F});
    const simd_float3 up{0.0F, 1.0F, 0.0F};
    simd_float3 direction{};
    if (moving_[static_cast<std::size_t>(CameraMove::forward)])
        direction += forward;
    if (moving_[static_cast<std::size_t>(CameraMove::backward)])
        direction -= forward;
    if (moving_[static_cast<std::size_t>(CameraMove::right)])
        direction += right;
    if (moving_[static_cast<std::size_t>(CameraMove::left)])
        direction -= right;
    if (moving_[static_cast<std::size_t>(CameraMove::up)])
        direction += up;
    if (moving_[static_cast<std::size_t>(CameraMove::down)])
        direction -= up;
    if (simd_length_squared(direction) > 1.0e-8F) {
        const float distance = movementSpeed_ * static_cast<float>(std::min(deltaSeconds, 0.1));
        position_ += simd_normalize(direction) * distance;
    }
}

void CameraController::clearMovement() noexcept {
    moving_.fill(false);
}

Transform CameraController::transform() const noexcept {
    Transform result;
    result.translation = position_;
    const simd_quatf yawRotation = simd_quaternion(yaw_, simd_float3{0.0F, 1.0F, 0.0F});
    const simd_quatf pitchRotation = simd_quaternion(pitch_, simd_float3{1.0F, 0.0F, 0.0F});
    result.rotation = simd_normalize(simd_mul(yawRotation, pitchRotation));
    return result;
}

void CameraController::setMovementSpeed(float metersPerSecond) noexcept {
    if (std::isfinite(metersPerSecond) && metersPerSecond > 0.0F) {
        movementSpeed_ = metersPerSecond;
    }
}

} // namespace aether::scene
