#include <aether/world_gaussian/GaussianRegionIndex.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace aether::world_gaussian {
namespace {

[[nodiscard]] Result<std::int32_t> cellCoordinate(float value, float cellSizeMeters) {
    if (!std::isfinite(value))
        return fail(ErrorCode::corruptData, "Gaussian position contains a non-finite coordinate");
    const double scaled =
        std::floor(static_cast<double>(value) / static_cast<double>(cellSizeMeters));
    constexpr double minimum = static_cast<double>(std::numeric_limits<std::int32_t>::min());
    constexpr double maximum = static_cast<double>(std::numeric_limits<std::int32_t>::max());
    if (scaled < minimum || scaled > maximum)
        return fail(ErrorCode::resourceExhausted, "Gaussian position exceeds dirty-grid range");
    return static_cast<std::int32_t>(scaled);
}

[[nodiscard]] Result<world::RegionKey>
regionKey(const gaussian::Gaussian& primitive, float cellSizeMeters) {
    auto x = cellCoordinate(primitive.position[0], cellSizeMeters);
    auto y = cellCoordinate(primitive.position[1], cellSizeMeters);
    auto z = cellCoordinate(primitive.position[2], cellSizeMeters);
    if (!x)
        return std::unexpected(x.error());
    if (!y)
        return std::unexpected(y.error());
    if (!z)
        return std::unexpected(z.error());
    return world::RegionKey{*x, *y, *z};
}

struct DirtyRegionInfo final {
    std::unordered_set<std::uint64_t> entityIds;
};

} // namespace

Result<GaussianRegionIndex> GaussianRegionIndex::create(const gaussian::GaussianAsset& asset,
                                                        float cellSizeMeters) {
    if (!std::isfinite(cellSizeMeters) || cellSizeMeters <= 0.0F)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian region index cell size must be finite and positive");

    GaussianRegionIndex result;
    result.cellSizeMeters_ = cellSizeMeters;
    result.gaussianCount_ = asset.gaussians.size();

    std::vector<std::pair<world::RegionKey, std::size_t>> keyed;
    keyed.reserve(asset.gaussians.size());
    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        auto key = regionKey(asset.gaussians[index], cellSizeMeters);
        if (!key)
            return std::unexpected(key.error());
        keyed.emplace_back(*key, index);
    }
    std::sort(keyed.begin(), keyed.end(), [](const auto& lhs, const auto& rhs) {
        if (lhs.first != rhs.first)
            return lhs.first < rhs.first;
        return lhs.second < rhs.second;
    });

    result.gaussianIndices_.reserve(keyed.size());
    for (std::size_t cursor = 0; cursor < keyed.size();) {
        const world::RegionKey key = keyed[cursor].first;
        const std::size_t first = result.gaussianIndices_.size();
        while (cursor < keyed.size() && keyed[cursor].first == key) {
            result.gaussianIndices_.push_back(keyed[cursor].second);
            ++cursor;
        }
        result.buckets_.push_back(Bucket{key, first, result.gaussianIndices_.size() - first});
    }
    return result;
}

GaussianRegionIndexStatistics GaussianRegionIndex::statistics() const noexcept {
    return {
        .regionBuckets = buckets_.size(),
        .indexedGaussians = gaussianCount_,
        .lowerBoundStorageBytes =
            buckets_.capacity() * sizeof(Bucket) +
            gaussianIndices_.capacity() * sizeof(std::size_t),
    };
}

Result<GaussianIndexedSelectionResult>
GaussianRegionIndex::select(const world::SelectiveUpdatePlan& worldUpdate,
                            const GaussianEntityOwnership* ownership,
                            GaussianLocalUpdatePolicy policy) const {
    if (!std::isfinite(worldUpdate.cellSizeMeters) || worldUpdate.cellSizeMeters <= 0.0F)
        return fail(ErrorCode::invalidArgument, "World update cell size must be finite and positive");
    if (worldUpdate.cellSizeMeters != cellSizeMeters_)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian region index cell size does not match world update cell size");
    if (policy.maximumAffectedGaussians == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian local-update budget cannot be zero");
    if (ownership && ownership->owners.size() != gaussianCount_)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian ownership count must match Gaussian asset primitive count");

    std::map<world::RegionKey, DirtyRegionInfo> dirty;
    for (const world::RegionUpdate& region : worldUpdate.dirtyRegions) {
        DirtyRegionInfo& info = dirty[region.key];
        for (const world::EntityId entity : region.entities) {
            if (entity.valid())
                info.entityIds.insert(entity.value);
        }
    }

    GaussianIndexedSelectionResult result;
    for (const auto& [key, info] : dirty) {
        ++result.statistics.dirtyBucketsVisited;
        const auto bucket = std::lower_bound(
            buckets_.begin(), buckets_.end(), key,
            [](const Bucket& candidate, const world::RegionKey& wanted) {
                return candidate.key < wanted;
            });
        if (bucket == buckets_.end() || bucket->key != key)
            continue;

        for (std::size_t offset = 0; offset < bucket->count; ++offset) {
            const std::size_t index = gaussianIndices_[bucket->first + offset];
            ++result.statistics.candidateGaussiansVisited;

            bool select = ownership == nullptr;
            if (ownership) {
                const world::EntityId owner = ownership->owners[index];
                if (!owner.valid()) {
                    select = policy.includeUnownedGaussians;
                    if (select)
                        ++result.selection.conservativeUnownedMatches;
                } else if (info.entityIds.contains(owner.value)) {
                    select = true;
                    ++result.selection.ownedMatches;
                } else {
                    ++result.selection.rejectedStableOwnedGaussians;
                }
            }

            if (!select)
                continue;
            if (result.selection.gaussianIndices.size() >= policy.maximumAffectedGaussians)
                return fail(ErrorCode::resourceExhausted,
                            "Gaussian local update exceeds affected-primitive budget");
            result.selection.gaussianIndices.push_back(index);
        }
    }

    std::sort(result.selection.gaussianIndices.begin(), result.selection.gaussianIndices.end());
    result.selection.unaffectedGaussians =
        gaussianCount_ - result.selection.gaussianIndices.size();
    return result;
}

} // namespace aether::world_gaussian
