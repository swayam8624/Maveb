#include <aether/scene/Camera.hpp>

#include <cmath>

namespace aether::scene {

Result<simd_float4x4> Camera::projectionMatrix(float aspectRatio) const {
    if (!std::isfinite(aspectRatio) || aspectRatio <= 0.0F || !std::isfinite(nearPlane) ||
        nearPlane <= 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Camera aspect ratio and near plane must be finite and positive");
    }

    if (projection == ProjectionType::perspective) {
        if (!std::isfinite(verticalFieldOfViewRadians) || verticalFieldOfViewRadians <= 0.0F ||
            verticalFieldOfViewRadians >= 3.1415926535F) {
            return fail(ErrorCode::invalidArgument, "Perspective field of view must be in (0, pi)");
        }
        if (!infiniteFarPlane && (!std::isfinite(farPlane) || farPlane <= nearPlane)) {
            return fail(ErrorCode::invalidArgument,
                        "Finite perspective far plane must be greater than near plane");
        }

        const float yScale = 1.0F / std::tan(verticalFieldOfViewRadians * 0.5F);
        const float xScale = yScale / aspectRatio;
        const float depthScale = infiniteFarPlane ? 0.0F : nearPlane / (farPlane - nearPlane);
        const float depthOffset =
            infiniteFarPlane ? nearPlane : (nearPlane * farPlane) / (farPlane - nearPlane);
        simd_float4x4 result{};
        result.columns[0] = {xScale, 0.0F, 0.0F, 0.0F};
        result.columns[1] = {0.0F, yScale, 0.0F, 0.0F};
        result.columns[2] = {0.0F, 0.0F, depthScale, -1.0F};
        result.columns[3] = {0.0F, 0.0F, depthOffset, 0.0F};
        return result;
    }

    if (!std::isfinite(orthographicHeight) || orthographicHeight <= 0.0F ||
        !std::isfinite(farPlane) || farPlane <= nearPlane) {
        return fail(ErrorCode::invalidArgument,
                    "Orthographic height must be positive and far must exceed near");
    }
    const float width = orthographicHeight * aspectRatio;
    const float depthRange = farPlane - nearPlane;
    simd_float4x4 result{};
    result.columns[0] = {2.0F / width, 0.0F, 0.0F, 0.0F};
    result.columns[1] = {0.0F, 2.0F / orthographicHeight, 0.0F, 0.0F};
    result.columns[2] = {0.0F, 0.0F, 1.0F / depthRange, 0.0F};
    result.columns[3] = {0.0F, 0.0F, farPlane / depthRange, 1.0F};
    return result;
}

Result<simd_float4x4> Camera::viewMatrix(const Transform& worldTransform) const {
    if (!isFinite(worldTransform) || !hasNonZeroScale(worldTransform)) {
        return fail(ErrorCode::invalidArgument,
                    "Camera transform must be finite and have non-zero scale");
    }
    return simd_inverse(worldTransform.matrix());
}

} // namespace aether::scene
