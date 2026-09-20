#pragma once

#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world/SelectiveUpdate.hpp>
#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <cstddef>
#include <vector>

namespace aether::world_gaussian {

struct GaussianRegionIndexStatistics final {
    std::size_t regionBuckets{};
    std::size_t indexedGaussians{};
    std::size_t lowerBoundStorageBytes{};
};

struct GaussianIndexedSelectionStatistics final {
    std::size_t dirtyBucketsVisited{};
    std::size_t candidateGaussiansVisited{};
};

struct GaussianIndexedSelectionResult final {
    GaussianLocalUpdateSelection selection;
    GaussianIndexedSelectionStatistics statistics;
};

/// Experimental exact spatial index for persistent-world local Gaussian selection.
///
/// The reference selector is semantically local but scans every Gaussian. This
/// prototype sorts primitive indices once by RegionKey and stores compact
/// contiguous bucket ranges. Dirty selection then performs a binary search per
/// RegionKey plus visits only candidate primitives in matching buckets.
class GaussianRegionIndex final {
  public:
    static Result<GaussianRegionIndex> create(const gaussian::GaussianAsset& asset,
                                              float cellSizeMeters);

    [[nodiscard]] Result<GaussianIndexedSelectionResult> select(
        const world::SelectiveUpdatePlan& worldUpdate,
        const GaussianEntityOwnership* ownership = nullptr,
        GaussianLocalUpdatePolicy policy = {}) const;

    [[nodiscard]] float cellSizeMeters() const noexcept {
        return cellSizeMeters_;
    }

    [[nodiscard]] GaussianRegionIndexStatistics statistics() const noexcept;

  private:
    struct Bucket final {
        world::RegionKey key{};
        std::size_t first{};
        std::size_t count{};
    };

    float cellSizeMeters_{};
    std::size_t gaussianCount_{};
    std::vector<Bucket> buckets_;
    std::vector<std::size_t> gaussianIndices_;
};

} // namespace aether::world_gaussian
