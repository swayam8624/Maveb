#include <aether/world_gaussian/GaussianOverlaySpatialIndex.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <new>
#include <utility>
#include <vector>

namespace aether::world_gaussian {
namespace {

struct RelocationUpdate final {
    std::uint32_t gaussianIndex{};
    world::RegionKey oldKey{};
    world::RegionKey newKey{};
};

[[nodiscard]] bool sameKey(const world::RegionKey& lhs, const world::RegionKey& rhs) noexcept {
    return lhs == rhs;
}

} // namespace

Result<GaussianOverlaySpatialIndex>
GaussianOverlaySpatialIndex::build(const gaussian::GaussianAsset& asset, float cellSizeMeters,
                                   GaussianOverlaySpatialIndexPolicy policy) {
    if (!std::isfinite(cellSizeMeters) || cellSizeMeters <= 0.0F) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian overlay index cell size must be finite and positive");
    }
    if (policy.maximumDeltaEntries == 0 || !std::isfinite(policy.compactionFraction) ||
        policy.compactionFraction <= 0.0 || policy.compactionFraction > 1.0) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian overlay index policy requires bounded positive delta and compaction");
    }

    GaussianOverlaySpatialIndex result(cellSizeMeters, policy);
    if (auto compacted = result.compact(asset); !compacted)
        return std::unexpected(compacted.error());
    return result;
}

Result<world::RegionKey> GaussianOverlaySpatialIndex::regionKey(simd_float3 position) const {
    if (!std::isfinite(position.x) || !std::isfinite(position.y) ||
        !std::isfinite(position.z)) {
        return fail(ErrorCode::corruptData,
                    "Gaussian overlay index received non-finite position");
    }

    const auto coordinate = [&](float value) -> Result<std::int32_t> {
        const double scaled =
            std::floor(static_cast<double>(value) / static_cast<double>(cellSizeMeters_));
        constexpr double minimum =
            static_cast<double>(std::numeric_limits<std::int32_t>::min());
        constexpr double maximum =
            static_cast<double>(std::numeric_limits<std::int32_t>::max());
        if (scaled < minimum || scaled > maximum) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian overlay index coordinate exceeds int32 range");
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

Result<void> GaussianOverlaySpatialIndex::compact(const gaussian::GaussianAsset& asset) {
    if (asset.gaussians.size() >
        static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index supports at most uint32 primitive indices");
    }

    std::vector<Entry> nextBase;
    try {
        nextBase.reserve(asset.gaussians.size());
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index could not allocate compact base");
    }

    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        const auto& primitive = asset.gaussians[index];
        auto key = regionKey(simd_float3{primitive.position[0], primitive.position[1],
                                         primitive.position[2]});
        if (!key)
            return std::unexpected(key.error());
        nextBase.push_back(Entry{*key, static_cast<std::uint32_t>(index)});
    }
    std::sort(nextBase.begin(), nextBase.end());

    std::vector<std::uint64_t> nextMovedBits;
    try {
        nextMovedBits.resize((asset.gaussians.size() + 63U) / 64U, 0U);
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index could not allocate relocation bitset");
    }

    baseByRegion_ = std::move(nextBase);
    movedBits_ = std::move(nextMovedBits);
    deltaByIndex_.clear();
    deltaByRegion_.clear();
    primitiveCount_ = asset.gaussians.size();
    return {};
}

bool GaussianOverlaySpatialIndex::baseContains(world::RegionKey key,
                                               std::uint32_t gaussianIndex) const noexcept {
    return std::binary_search(baseByRegion_.begin(), baseByRegion_.end(),
                              Entry{key, gaussianIndex});
}

bool GaussianOverlaySpatialIndex::moved(std::uint32_t gaussianIndex) const noexcept {
    const std::size_t word = gaussianIndex / 64U;
    const std::size_t bit = gaussianIndex % 64U;
    return word < movedBits_.size() &&
           (movedBits_[word] & (std::uint64_t{1} << bit)) != 0;
}

void GaussianOverlaySpatialIndex::setMoved(std::uint32_t gaussianIndex) noexcept {
    const std::size_t word = gaussianIndex / 64U;
    const std::size_t bit = gaussianIndex % 64U;
    if (word < movedBits_.size())
        movedBits_[word] |= std::uint64_t{1} << bit;
}

Result<void>
GaussianOverlaySpatialIndex::applyRelocations(std::span<const GaussianRelocation> relocations) {
    if (relocations.empty())
        return {};
    if (primitiveCount_ >
        static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index primitive cardinality exceeds uint32 range");
    }

    std::vector<RelocationUpdate> updates;
    try {
        updates.reserve(relocations.size());
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index could not allocate relocation transaction");
    }

    for (const GaussianRelocation& relocation : relocations) {
        if (relocation.gaussianIndex >= primitiveCount_) {
            return fail(ErrorCode::invalidArgument,
                        "Gaussian overlay relocation primitive index is out of range");
        }
        auto oldKey = regionKey(relocation.oldPosition);
        auto newKey = regionKey(relocation.newPosition);
        if (!oldKey)
            return std::unexpected(oldKey.error());
        if (!newKey)
            return std::unexpected(newKey.error());
        updates.push_back(RelocationUpdate{
            static_cast<std::uint32_t>(relocation.gaussianIndex), *oldKey, *newKey});
    }

    std::sort(updates.begin(), updates.end(), [](const RelocationUpdate& lhs,
                                                 const RelocationUpdate& rhs) {
        return lhs.gaussianIndex < rhs.gaussianIndex;
    });
    for (std::size_t index = 1; index < updates.size(); ++index) {
        if (updates[index - 1].gaussianIndex == updates[index].gaussianIndex) {
            return fail(ErrorCode::invalidArgument,
                        "Gaussian overlay relocation batch contains duplicate primitive index");
        }
    }

    for (const RelocationUpdate& update : updates) {
        const auto delta = std::lower_bound(
            deltaByIndex_.begin(), deltaByIndex_.end(), update.gaussianIndex,
            [](const DeltaByIndex& candidate, std::uint32_t wanted) {
                return candidate.gaussianIndex < wanted;
            });

        if (delta != deltaByIndex_.end() && delta->gaussianIndex == update.gaussianIndex) {
            if (!moved(update.gaussianIndex) || !sameKey(delta->key, update.oldKey)) {
                return fail(ErrorCode::corruptData,
                            "Gaussian overlay relocation old position disagrees with delta state");
            }
        } else {
            if (moved(update.gaussianIndex)) {
                return fail(ErrorCode::corruptData,
                            "Gaussian overlay relocation bitset and delta state disagree");
            }
            if (!baseContains(update.oldKey, update.gaussianIndex)) {
                return fail(ErrorCode::invalidArgument,
                            "Gaussian overlay relocation old position is stale");
            }
        }
    }

    std::vector<DeltaByIndex> nextByIndex;
    try {
        nextByIndex.reserve(deltaByIndex_.size() + updates.size());
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index could not allocate next delta state");
    }

    std::size_t oldCursor{};
    std::size_t updateCursor{};
    while (oldCursor < deltaByIndex_.size() || updateCursor < updates.size()) {
        if (updateCursor == updates.size() ||
            (oldCursor < deltaByIndex_.size() &&
             deltaByIndex_[oldCursor].gaussianIndex < updates[updateCursor].gaussianIndex)) {
            nextByIndex.push_back(deltaByIndex_[oldCursor++]);
            continue;
        }

        if (oldCursor < deltaByIndex_.size() &&
            deltaByIndex_[oldCursor].gaussianIndex == updates[updateCursor].gaussianIndex) {
            ++oldCursor;
        }

        const RelocationUpdate& update = updates[updateCursor++];
        if (!baseContains(update.newKey, update.gaussianIndex)) {
            nextByIndex.push_back(DeltaByIndex{update.gaussianIndex, update.newKey});
        }
    }

    if (nextByIndex.size() > policy_.maximumDeltaEntries) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay relocation exceeds configured delta-entry budget");
    }

    std::vector<Entry> nextByRegion;
    std::vector<std::uint64_t> nextMovedBits;
    try {
        nextByRegion.reserve(nextByIndex.size());
        nextMovedBits.resize((primitiveCount_ + 63U) / 64U, 0U);
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay index could not allocate derived delta state");
    }

    for (const DeltaByIndex& delta : nextByIndex) {
        nextByRegion.push_back(Entry{delta.key, delta.gaussianIndex});
        const std::size_t word = delta.gaussianIndex / 64U;
        const std::size_t bit = delta.gaussianIndex % 64U;
        nextMovedBits[word] |= std::uint64_t{1} << bit;
    }
    std::sort(nextByRegion.begin(), nextByRegion.end());

    deltaByIndex_ = std::move(nextByIndex);
    deltaByRegion_ = std::move(nextByRegion);
    movedBits_ = std::move(nextMovedBits);
    return {};
}

Result<GaussianOverlayRegionQueryStatistics>
GaussianOverlaySpatialIndex::appendIndices(world::RegionKey key,
                                           std::vector<std::size_t>& output,
                                           std::size_t maximumOutputSize) const {
    if (maximumOutputSize == 0 || output.size() > maximumOutputSize) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian overlay query output budget is invalid");
    }

    const Entry lower{key, 0};
    const Entry upper{key, std::numeric_limits<std::uint32_t>::max()};
    const auto baseFirst = std::lower_bound(baseByRegion_.begin(), baseByRegion_.end(), lower);
    const auto baseLast = std::upper_bound(baseByRegion_.begin(), baseByRegion_.end(), upper);
    const auto deltaFirst = std::lower_bound(deltaByRegion_.begin(), deltaByRegion_.end(), lower);
    const auto deltaLast = std::upper_bound(deltaByRegion_.begin(), deltaByRegion_.end(), upper);

    GaussianOverlayRegionQueryStatistics statistics;
    std::size_t appendCount{};
    for (auto it = baseFirst; it != baseLast; ++it) {
        ++statistics.baseEntriesVisited;
        if (moved(it->gaussianIndex)) {
            ++statistics.staleBaseEntriesSkipped;
            continue;
        }
        ++appendCount;
    }
    statistics.deltaEntriesVisited =
        static_cast<std::size_t>(std::distance(deltaFirst, deltaLast));
    appendCount += statistics.deltaEntriesVisited;

    if (appendCount > maximumOutputSize - output.size()) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay query exceeds configured output budget");
    }

    try {
        output.reserve(output.size() + appendCount);
    } catch (const std::bad_alloc&) {
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian overlay query could not reserve output storage");
    }

    for (auto it = baseFirst; it != baseLast; ++it) {
        if (!moved(it->gaussianIndex))
            output.push_back(it->gaussianIndex);
    }
    for (auto it = deltaFirst; it != deltaLast; ++it)
        output.push_back(it->gaussianIndex);

    statistics.currentIndicesAppended = appendCount;
    return statistics;
}

GaussianOverlaySpatialIndexStatistics GaussianOverlaySpatialIndex::statistics() const noexcept {
    const double fraction =
        primitiveCount_ == 0
            ? 0.0
            : static_cast<double>(deltaByIndex_.size()) /
                  static_cast<double>(primitiveCount_);
    return {
        .primitiveCount = primitiveCount_,
        .baseEntries = baseByRegion_.size(),
        .deltaEntries = deltaByIndex_.size(),
        .movedPrimitives = deltaByIndex_.size(),
        .lowerBoundStorageBytes =
            baseByRegion_.capacity() * sizeof(Entry) +
            deltaByIndex_.capacity() * sizeof(DeltaByIndex) +
            deltaByRegion_.capacity() * sizeof(Entry) +
            movedBits_.capacity() * sizeof(std::uint64_t),
        .compactionRecommended = fraction >= policy_.compactionFraction,
    };
}

} // namespace aether::world_gaussian
