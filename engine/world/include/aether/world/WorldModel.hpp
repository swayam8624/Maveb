#pragma once

#include <aether/world/EntityAssociation.hpp>
#include <aether/world/SelectiveUpdate.hpp>

#include <cstdint>
#include <vector>

namespace aether::world {

/// Policies governing one observation-to-world transaction.
struct WorldIngestPolicy final {
    AssociationPolicy association;
    DiffPolicy diff;
    SelectiveUpdatePolicy selectiveUpdate;
};

/// Complete, immutable result of one committed world-model update.
struct WorldIngestResult final {
    std::uint64_t revision{};
    WorldDiff diff;
    SelectiveUpdatePlan selectiveUpdate;
    std::size_t reusedIds{};
    std::size_t createdIds{};
    std::size_t missingPreviousEntities{};
};

/// Transactional persistent model of a captured physical world.
///
/// Ingest performs the entire temporal pipeline before mutating committed state:
///
/// observations -> stable-ID association -> candidate snapshot -> Reality Diff -> selective
/// update plan -> append-only commit
///
/// If association, validation, diffing, update planning, or dirty-region budgeting fails, neither
/// the timeline nor the ID allocator advances. This gives Studio/reconstruction one high-level
/// operation with deterministic rollback semantics rather than requiring callers to coordinate
/// partially committed subsystems.
class PersistentWorldModel final {
  public:
    [[nodiscard]] Result<WorldIngestResult>
    ingest(TimestampNs timestamp, std::vector<EntityState> observations,
           WorldIngestPolicy policy = {});

    [[nodiscard]] const WorldTimeline& timeline() const noexcept {
        return timeline_;
    }

    [[nodiscard]] const WorldSnapshot* latest() const noexcept {
        return timeline_.latest();
    }

    [[nodiscard]] std::uint64_t nextEntityId() const noexcept {
        return nextEntityId_;
    }

  private:
    WorldTimeline timeline_;
    std::uint64_t nextEntityId_{1};
};

} // namespace aether::world
