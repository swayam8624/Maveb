#pragma once

#include <aether/world_gaussian/GaussianLocalUpdate.hpp>

#include <cstddef>

namespace aether::world_gaussian {

struct GaussianOwnershipAssignmentPolicy final {
    float maximumSurfaceDistanceMeters{0.10F};
    std::size_t maximumCandidatePairs{50'000'000};
    bool requireGaussianRepresentation{true};
};

struct GaussianOwnershipAssignmentResult final {
    GaussianEntityOwnership ownership;
    std::size_t assignedGaussians{};
    std::size_t unassignedGaussians{};
    std::size_t candidatePairs{};
};

/// Assigns each Gaussian point to the most plausible persistent entity in one immutable revision.
///
/// Candidate generation sweeps Gaussian X coordinates against expanded entity AABB X intervals.
/// Candidates are then ranked by point-to-AABB distance, with containing entities preferred and
/// smaller containers winning ties so a cup is favored over the room containing it. Stable ID is
/// the final deterministic tie-break. A hard candidate budget bounds dense/adversarial scenes.
[[nodiscard]] Result<GaussianOwnershipAssignmentResult>
assignGaussianOwnership(const gaussian::GaussianAsset& asset, const world::WorldSnapshot& snapshot,
                        GaussianOwnershipAssignmentPolicy policy = {});

} // namespace aether::world_gaussian
