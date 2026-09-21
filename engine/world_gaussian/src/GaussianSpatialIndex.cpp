#include <aether/world_gaussian/GaussianSpatialIndex.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace aether::world_gaussian {

std::size_t
GaussianSpatialIndex::RegionKeyHash::operator()(const world::RegionKey& key) const noexcept {
    std::size_t seed = std::hash<std::int32_t>{}(key.x);
    const auto combine = [&seed](std::int32_t value) {
        const std::size_t hashed = std::hash<std::int32_t>{}(value);
        seed ^=
            hashed + static_cast<std::size_t>(0x9e3779b97f4a7c15ULL) + (seed << 6U) + (seed >> 2U);
    };
    combine(key.y);
    combine(key.z);
    return seed;
}

Result<world::RegionKey> GaussianSpatialIndex::regionKey(simd_float3 position) const {
    if (!std::isfinite(position.x) || !std::isfinite(position.y) || !std::isfinite(position.z)) {
        return fail(ErrorCode::corruptData, "Gaussian spatial index received non-finite position");
    }
    const auto coordinate = [&](float value) -> Result<std::int32_t> {
        const double scaled =
            std::floor(static_cast<double>(value) / static_cast<double>(cellSizeMeters_));
        constexpr double minimum = static_cast<double>(std::numeric_limits<std::int32_t>::min());
        constexpr double maximum = static_cast<double>(std::numeric_limits<std::int32_t>::max());
        if (scaled < minimum || scaled > maximum) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian spatial index coordinate exceeds int32 range");
        }
        return static_cast<std::int32_t>(scaled);
    };
    auto x = coordinate(position.x);
    auto y = coordinate(position.y);
    auto z = coordinate(position.z);
    if (!x)
        return std::unexpected(x.error());
    if (!y)
        return std::unexpected(y.error());
    if (!z)
        return std::unexpected(z.error());
    return world::RegionKey{*x, *y, *z};
}

Result<GaussianSpatialIndex> GaussianSpatialIndex::build(const gaussian::GaussianAsset& asset,
                                                         float cellSizeMeters) {
    if (!std::isfinite(cellSizeMeters) || cellSizeMeters <= 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian spatial index cell size must be finite and positive");
    }
    GaussianSpatialIndex result(cellSizeMeters);
    if (auto rebuilt = result.rebuild(asset); !rebuilt)
        return std::unexpected(rebuilt.error());
    return result;
}

Result<void> GaussianSpatialIndex::rebuild(const gaussian::GaussianAsset& asset) {
    std::unordered_map<world::RegionKey, std::vector<std::size_t>, RegionKeyHash> next;
    next.reserve(std::min(asset.gaussians.size(), static_cast<std::size_t>(1'000'000)));
    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        const auto& primitive = asset.gaussians[index];
        auto key = regionKey(
            simd_float3{primitive.position[0], primitive.position[1], primitive.position[2]});
        if (!key)
            return std::unexpected(key.error());
        next[*key].push_back(index);
    }
    buckets_ = std::move(next);
    primitiveCount_ = asset.gaussians.size();
    return {};
}

Result<void> GaussianSpatialIndex::relocateGaussian(std::size_t gaussianIndex,
                                                    simd_float3 oldPosition,
                                                    simd_float3 newPosition) {
    if (gaussianIndex >= primitiveCount_) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian spatial index relocation primitive is out of range");
    }
    auto oldKey = regionKey(oldPosition);
    auto newKey = regionKey(newPosition);
    if (!oldKey)
        return std::unexpected(oldKey.error());
    if (!newKey)
        return std::unexpected(newKey.error());
    if (*oldKey == *newKey)
        return {};

    auto oldBucket = buckets_.find(*oldKey);
    if (oldBucket == buckets_.end()) {
        return fail(ErrorCode::corruptData,
                    "Gaussian spatial index relocation missing old region bucket");
    }
    auto found = std::find(oldBucket->second.begin(), oldBucket->second.end(), gaussianIndex);
    if (found == oldBucket->second.end()) {
        return fail(ErrorCode::corruptData,
                    "Gaussian spatial index relocation missing primitive membership");
    }
    *found = oldBucket->second.back();
    oldBucket->second.pop_back();
    if (oldBucket->second.empty())
        buckets_.erase(oldBucket);
    buckets_[*newKey].push_back(gaussianIndex);
    return {};
}

std::span<const std::size_t> GaussianSpatialIndex::indices(world::RegionKey key) const noexcept {
    const auto found = buckets_.find(key);
    if (found == buckets_.end())
        return {};
    return found->second;
}

GaussianSpatialIndex::Statistics GaussianSpatialIndex::statistics() const noexcept {
    std::size_t entries{};
    for (const auto& [key, values] : buckets_) {
        static_cast<void>(key);
        entries += values.size();
    }
    return Statistics{.primitiveCount = primitiveCount_,
                      .occupiedRegions = buckets_.size(),
                      .storedIndexEntries = entries};
}

} // namespace aether::world_gaussian
