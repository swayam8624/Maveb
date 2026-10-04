#pragma once

#include <aether/core/Error.hpp>

#include <simd/simd.h>

namespace aether::scene {

/// Translation, rotation, and scale for an entity.
///
/// Input convention: right-handed world, meters, unit quaternion, non-zero scale.
/// Output convention: column-major matrices multiplied by column vectors, matching Apple SIMD/MSL.
/// Task: retain editor-friendly TRS state while producing GPU-compatible matrices without
/// transpose.
struct Transform final {
    simd_float3 translation{0.0F, 0.0F, 0.0F};
    simd_quatf rotation = simd_quaternion(0.0F, 0.0F, 0.0F, 1.0F);
    simd_float3 scale{1.0F, 1.0F, 1.0F};

    [[nodiscard]] static Transform identity() noexcept {
        return {};
    }
    [[nodiscard]] simd_float4x4 matrix() const noexcept;
};

[[nodiscard]] bool isFinite(const Transform& transform) noexcept;
[[nodiscard]] bool hasNonZeroScale(const Transform& transform, float epsilon = 1.0e-6F) noexcept;
/// Decomposes a finite affine matrix into editor TRS, rejecting perspective, shear, and degeneracy.
[[nodiscard]] Result<Transform> decomposeTransform(simd_float4x4 matrix,
                                                   float tolerance = 1.0e-4F);

} // namespace aether::scene
