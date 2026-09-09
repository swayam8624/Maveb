#pragma once

#include <aether/world/EntityAssociation.hpp>
#include <aether/world/SelectiveUpdate.hpp>
#include <aether/world/WorldArchive.hpp>
#include <aether/world/WorldEdit.hpp>

#include <cstdint>
#include <filesystem>
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

/// Result of restoring a historical world state as a new append-only revision.
struct WorldRevertResult final {
    std::uint64_t revision{};
    std::uint64_t sourceRevision{};
    WorldDiff diff;
    SelectiveUpdatePlan selectiveUpdate;
};

/// Transactional persistent model of a captured physical world.
///
/// Observation ingestion, authored edits, and historical restores compute their complete candidate
/// diff/update plan before mutating committed history. Failed work therefore cannot consume entity
/// IDs or append a partial revision.
class PersistentWorldModel final {
  public:
    [[nodiscard]] Result<WorldIngestResult> ingest(TimestampNs timestamp,
                                                   std::vector<EntityState> observations,
                                                   WorldIngestPolicy policy = {});

    /// Applies sparse authored mutations to stable persistent entities as one world revision.
    [[nodiscard]] Result<WorldEditResult> edit(TimestampNs timestamp,
                                               const std::vector<EntityPatch>& patches,
                                               WorldEditPolicy policy = {});

    /// Restores a historical snapshot as a new revision without deleting later history or rolling
    /// back the persistent-ID allocator. This is the primitive behind non-destructive time travel.
    [[nodiscard]] Result<WorldRevertResult> revertTo(std::uint64_t sourceRevision,
                                                      TimestampNs timestamp,
                                                      WorldEditPolicy policy = {});

    /// Atomically persists the complete committed history and identity allocator state.
    [[nodiscard]] Result<void> save(const std::filesystem::path& path) const;

    /// Restores a complete persistent-world model from a validated versioned archive.
    [[nodiscard]] static Result<PersistentWorldModel> load(const std::filesystem::path& path,
                                                           WorldArchiveLimits limits = {});

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
