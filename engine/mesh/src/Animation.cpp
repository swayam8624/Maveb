#include <aether/mesh/Animation.hpp>

#include <algorithm>
#include <cmath>
#include <functional>

namespace aether::mesh {
namespace {
simd_float4 valueAt(const AnimationChannel& channel, std::size_t key, std::size_t component) {
    return channel.interpolation == AnimationInterpolation::cubicSpline
               ? channel.values[key * 3 + component]
               : channel.values[key];
}

simd_float4 interpolate(const AnimationChannel& channel, std::size_t first, std::size_t second,
                        float alpha, float interval) {
    if (channel.interpolation == AnimationInterpolation::step || first == second)
        return valueAt(channel, first, 1);
    if (channel.interpolation == AnimationInterpolation::linear) {
        const auto a = valueAt(channel, first, 1);
        const auto b = valueAt(channel, second, 1);
        if (channel.path == AnimationPath::rotation) {
            return simd_slerp(simd_quatf{a}, simd_quatf{b}, alpha).vector;
        }
        return simd_mix(a, b, simd_float4{alpha, alpha, alpha, alpha});
    }
    const auto p0 = valueAt(channel, first, 1);
    const auto m0 = valueAt(channel, first, 2) * interval;
    const auto p1 = valueAt(channel, second, 1);
    const auto m1 = valueAt(channel, second, 0) * interval;
    const float t2 = alpha * alpha;
    const float t3 = t2 * alpha;
    auto result = (2.0F * t3 - 3.0F * t2 + 1.0F) * p0 +
                  (t3 - 2.0F * t2 + alpha) * m0 + (-2.0F * t3 + 3.0F * t2) * p1 +
                  (t3 - t2) * m1;
    if (channel.path == AnimationPath::rotation) {
        result = simd_length_squared(result) > 1.0e-12F ? simd_normalize(result) : p0;
    }
    return result;
}
} // namespace

Result<std::vector<scene::Transform>> sampleAnimation(const MeshAsset& asset, std::size_t clipIndex,
                                                       float seconds, bool loop) {
    if (clipIndex >= asset.animations.size())
        return fail(ErrorCode::invalidArgument, "Animation clip index is out of range");
    if (!std::isfinite(seconds))
        return fail(ErrorCode::invalidArgument, "Animation sample time must be finite");
    std::vector<scene::Transform> result;
    result.reserve(asset.nodes.size());
    for (const auto& node : asset.nodes) result.push_back(node.localTransform);
    const auto& clip = asset.animations[clipIndex];
    float time = seconds;
    if (clip.durationSeconds > 0.0F) {
        if (loop) {
            time = std::fmod(seconds, clip.durationSeconds);
            if (time < 0.0F) time += clip.durationSeconds;
        } else {
            time = std::clamp(seconds, 0.0F, clip.durationSeconds);
        }
    }
    for (const auto& channel : clip.channels) {
        if (channel.nodeIndex >= result.size() || channel.keyTimes.empty())
            return fail(ErrorCode::corruptData, "Animation channel references invalid node or keys");
        auto upper = std::upper_bound(channel.keyTimes.begin(), channel.keyTimes.end(), time);
        const std::size_t second = upper == channel.keyTimes.end()
                                       ? channel.keyTimes.size() - 1
                                       : static_cast<std::size_t>(upper - channel.keyTimes.begin());
        const std::size_t first = second == 0 ? 0 : second - 1;
        const float interval = channel.keyTimes[second] - channel.keyTimes[first];
        const float alpha = interval > 0.0F ? (time - channel.keyTimes[first]) / interval : 0.0F;
        const auto value = interpolate(channel, first, second, alpha, interval);
        auto& transform = result[channel.nodeIndex];
        switch (channel.path) {
        case AnimationPath::translation: transform.translation = value.xyz; break;
        case AnimationPath::rotation: transform.rotation = simd_normalize(simd_quatf{value}); break;
        case AnimationPath::scale: transform.scale = value.xyz; break;
        }
    }
    for (const auto& transform : result) {
        if (!scene::isFinite(transform) || !scene::hasNonZeroScale(transform))
            return fail(ErrorCode::corruptData,
                        "Animation produced a non-finite or singular node transform");
    }
    return result;
}

Result<std::vector<simd_float4x4>> resolveWorldTransforms(
    const MeshAsset& asset, std::span<const scene::Transform> localTransforms) {
    if (localTransforms.size() != asset.nodes.size())
        return fail(ErrorCode::invalidArgument, "Local transform count does not match scene nodes");
    std::vector<simd_float4x4> result(asset.nodes.size(), matrix_identity_float4x4);
    std::vector<std::uint8_t> state(asset.nodes.size());
    std::function<Result<void>(std::size_t)> resolve = [&](std::size_t index) -> Result<void> {
        if (index >= asset.nodes.size()) return fail(ErrorCode::corruptData, "Scene node index is invalid");
        if (state[index] == 2) return {};
        if (state[index] == 1) return fail(ErrorCode::corruptData, "Scene node hierarchy contains a cycle");
        state[index] = 1;
        const auto local = localTransforms[index].matrix();
        if (asset.nodes[index].parentIndex) {
            const auto parent = *asset.nodes[index].parentIndex;
            if (auto parentResult = resolve(parent); !parentResult) return parentResult;
            result[index] = simd_mul(result[parent], local);
        } else {
            result[index] = local;
        }
        state[index] = 2;
        return {};
    };
    for (std::size_t index = 0; index < asset.nodes.size(); ++index)
        if (auto resolved = resolve(index); !resolved) return std::unexpected(resolved.error());
    return result;
}

} // namespace aether::mesh
