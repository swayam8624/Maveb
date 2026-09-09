#pragma once

#include <aether/world/PersistentWorld.hpp>

#include <cstddef>
#include <cstdint>
#include <vector>

namespace aether::world {

/// Deterministic baseline policy for carrying physical entity identity between observations.
/// This is deliberately geometry-first and bounded; future learned/semantic trackers can replace
/// the scoring implementation without changing the persistent-world contract.
struct AssociationPolicy final {
    float maximumCenterDistanceMeters{1.5F};
    float minimumScore{0.20F};
    std::size_t maximumCandidatePairs{2'000'000};
    bool allowSemanticMismatch{false};
};

struct AssociationResult final {
    WorldSnapshot snapshot;
    std::size_t reusedIds{};
    std::size_t createdIds{};
    std::size_t missingPreviousEntities{};
    std::uint64_t nextEntityId{1};
};

/// Assigns stable IDs to a new set of reconstructed/observed entity states.
///
/// Valid non-zero IDs supplied by an upstream tracker are authoritative. Unassigned observations
/// (`id == 0`) are matched globally and deterministically against unmatched previous entities using
/// semantic compatibility, metric center distance, bounds overlap, and representation signatures.
/// Remaining observations receive fresh monotonically increasing IDs.
[[nodiscard]] Result<AssociationResult> associateObservations(const WorldSnapshot& previous,
                                                              TimestampNs timestamp,
                                                              std::vector<EntityState> observations,
                                                              std::uint64_t nextEntityId,
                                                              AssociationPolicy policy = {});

} // namespace aether::world
