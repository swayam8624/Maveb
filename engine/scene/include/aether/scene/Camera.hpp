#pragma once

#include <aether/core/Error.hpp>
#include <aether/scene/Transform.hpp>

#include <simd/simd.h>

namespace aether::scene {

enum class ProjectionType { perspective, orthographic };

struct Camera final {
    ProjectionType projection{ProjectionType::perspective};
    float verticalFieldOfViewRadians{1.0471975512F};
    float nearPlane{0.05F};
    float farPlane{10'000.0F};
    float orthographicHeight{10.0F};
    bool infiniteFarPlane{true};

    /// Input: positive viewport aspect ratio.
    /// Output: reverse-Z projection with Metal's [0,1] depth range.
    /// Task: maximize near-camera depth precision and preserve MSL matrix layout.
    [[nodiscard]] Result<simd_float4x4> projectionMatrix(float aspectRatio) const;

    /// Input: finite camera world transform with non-zero scale.
    /// Output: world-to-view matrix.
    /// Task: transform world-space geometry into the camera's right-handed view space.
    [[nodiscard]] Result<simd_float4x4> viewMatrix(const Transform& worldTransform) const;
};

} // namespace aether::scene
