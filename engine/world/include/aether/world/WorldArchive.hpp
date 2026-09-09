#pragma once

#include <aether/world/PersistentWorld.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <vector>

namespace aether::world {

inline constexpr std::uint64_t worldArchiveSchemaVersion = 1;

struct WorldArchiveLimits final {
    std::size_t maximumSnapshots{100000};
    std::size_t maximumEntitiesPerSnapshot{10000000};
    std::size_t maximumTotalEntities{50000000};
};

struct WorldArchiveData final {
    std::uint64_t nextEntityId{1};
    std::vector<WorldSnapshot> snapshots;
};

/// Atomically writes the complete temporal world history to a versioned JSON archive.
/// The destination is replaced only after the full payload has been validated and written.
[[nodiscard]] Result<void> saveWorldArchive(const std::filesystem::path& path,
                                            const WorldTimeline& timeline,
                                            std::uint64_t nextEntityId);

/// Loads and validates a versioned persistent-world archive with explicit resource limits.
[[nodiscard]] Result<WorldArchiveData>
loadWorldArchive(const std::filesystem::path& path, WorldArchiveLimits limits = {});

} // namespace aether::world
