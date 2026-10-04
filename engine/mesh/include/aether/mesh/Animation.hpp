#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <span>

namespace aether::mesh {

/// Samples a clip into a complete local-transform snapshot without mutating the asset.
/// Time is wrapped for looping playback and clamped otherwise.
[[nodiscard]] Result<std::vector<scene::Transform>> sampleAnimation(
    const MeshAsset& asset, std::size_t clipIndex, float seconds, bool loop);

/// Resolves a local-transform snapshot into node world matrices with cycle/index validation.
[[nodiscard]] Result<std::vector<simd_float4x4>> resolveWorldTransforms(
    const MeshAsset& asset, std::span<const scene::Transform> localTransforms);

} // namespace aether::mesh
