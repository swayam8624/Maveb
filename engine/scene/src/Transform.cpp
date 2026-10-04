#include <aether/scene/Transform.hpp>

#include <cmath>
#include <algorithm>

namespace aether::scene {

simd_float4x4 Transform::matrix() const noexcept {
    simd_float4x4 translationMatrix = matrix_identity_float4x4;
    translationMatrix.columns[3] = {translation.x, translation.y, translation.z, 1.0F};

    simd_float4x4 rotationMatrix = simd_matrix4x4(simd_normalize(rotation));
    simd_float4x4 scaleMatrix = matrix_identity_float4x4;
    scaleMatrix.columns[0].x = scale.x;
    scaleMatrix.columns[1].y = scale.y;
    scaleMatrix.columns[2].z = scale.z;
    return simd_mul(translationMatrix, simd_mul(rotationMatrix, scaleMatrix));
}

bool isFinite(const Transform& transform) noexcept {
    const auto vectorFinite = [](simd_float3 value) {
        return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
    };
    const simd_float4 quaternion = transform.rotation.vector;
    return vectorFinite(transform.translation) && vectorFinite(transform.scale) &&
           std::isfinite(quaternion.x) && std::isfinite(quaternion.y) &&
           std::isfinite(quaternion.z) && std::isfinite(quaternion.w);
}

bool hasNonZeroScale(const Transform& transform, float epsilon) noexcept {
    return std::abs(transform.scale.x) > epsilon && std::abs(transform.scale.y) > epsilon &&
           std::abs(transform.scale.z) > epsilon;
}

Result<Transform> decomposeTransform(simd_float4x4 matrix, float tolerance) {
    if (!std::isfinite(tolerance) || tolerance <= 0.0F)
        return fail(ErrorCode::invalidArgument, "Transform decomposition tolerance is invalid");
    for (const auto column : matrix.columns)
        for (std::size_t row = 0; row < 4; ++row)
            if (!std::isfinite(column[row]))
                return fail(ErrorCode::invalidArgument, "Transform matrix is not finite");
    if (std::abs(matrix.columns[0].w) > tolerance ||
        std::abs(matrix.columns[1].w) > tolerance ||
        std::abs(matrix.columns[2].w) > tolerance ||
        std::abs(matrix.columns[3].w - 1.0F) > tolerance)
        return fail(ErrorCode::unsupported, "Transform matrix contains perspective");

    simd_float3 basisX = matrix.columns[0].xyz;
    simd_float3 basisY = matrix.columns[1].xyz;
    simd_float3 basisZ = matrix.columns[2].xyz;
    simd_float3 scale{simd_length(basisX), simd_length(basisY), simd_length(basisZ)};
    if (scale.x <= tolerance || scale.y <= tolerance || scale.z <= tolerance)
        return fail(ErrorCode::invalidArgument, "Transform matrix has degenerate scale");
    if (simd_dot(simd_cross(basisX, basisY), basisZ) < 0.0F) scale.x = -scale.x;
    basisX /= scale.x;
    basisY /= scale.y;
    basisZ /= scale.z;
    const float orthogonality = std::max({std::abs(simd_dot(basisX, basisY)),
                                          std::abs(simd_dot(basisX, basisZ)),
                                          std::abs(simd_dot(basisY, basisZ))});
    if (orthogonality > tolerance)
        return fail(ErrorCode::unsupported, "Transform matrix contains shear");
    const simd_float3x3 rotationMatrix{basisX, basisY, basisZ};
    Transform result;
    result.translation = matrix.columns[3].xyz;
    result.rotation = simd_normalize(simd_quaternion(rotationMatrix));
    result.scale = scale;
    return result;
}

} // namespace aether::scene
