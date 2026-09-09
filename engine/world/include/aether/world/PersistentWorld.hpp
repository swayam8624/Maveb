#pragma once

#include <aether/core/Error.hpp>
#include <aether/scene/Transform.hpp>

#include <compare>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace aether::world {

using TimestampNs = std::uint64_t;

/// Stable identity for a physical or authored entity across temporal observations.
/// Zero is reserved as an invalid/unassigned identifier.
struct EntityId final {
    std::uint64_t value{};

    [[nodiscard]] constexpr bool valid() const noexcept {
        return value != 0;
    }

    auto operator<=>(const EntityId&) const = default;
};

/// Axis-aligned bounds expressed in the persistent world's metric coordinate frame.
struct Bounds final {
    simd_float3 minimum{};
    simd_float3 maximum{};
};

enum class RepresentationKind : std::uint8_t {
    unknown,
    mesh,
    gaussian,
    hybrid,
    volumetric,
};

/// Persistent state of one spatial entity at a particular world revision.
///
/// geometrySignature and appearanceSignature are intentionally opaque. Producers may bind them to
/// canonical-asset hashes, topology versions, Gaussian field revisions, material hashes, or another
/// deterministic representation identity. The temporal layer only needs stable equality semantics.
struct EntityState final {
    EntityId id{};
    std::string name;
    std::string semanticLabel;
    scene::Transform transform;
    Bounds worldBounds;
    RepresentationKind representation{RepresentationKind::unknown};
    std::uint64_t geometrySignature{};
    std::uint64_t appearanceSignature{};
    float confidence{1.0F};
    TimestampNs lastObserved{};
};

/// Immutable logical state of the persistent world at one instant.
/// revision is assigned by WorldTimeline when appended.
struct WorldSnapshot final {
    std::uint64_t revision{};
    TimestampNs timestamp{};
    std::vector<EntityState> entities;
};

enum class ChangeFlag : std::uint16_t {
    none = 0,
    added = 1U << 0U,
    removed = 1U << 1U,
    translated = 1U << 2U,
    rotated = 1U << 3U,
    scaled = 1U << 4U,
    geometry = 1U << 5U,
    appearance = 1U << 6U,
    semantic = 1U << 7U,
    confidence = 1U << 8U,
    representation = 1U << 9U,
    bounds = 1U << 10U,
    metadata = 1U << 11U,
};

[[nodiscard]] constexpr ChangeFlag operator|(ChangeFlag lhs, ChangeFlag rhs) noexcept {
    return static_cast<ChangeFlag>(static_cast<std::uint16_t>(lhs) |
                                   static_cast<std::uint16_t>(rhs));
}

constexpr ChangeFlag& operator|=(ChangeFlag& lhs, ChangeFlag rhs) noexcept {
    lhs = lhs | rhs;
    return lhs;
}

[[nodiscard]] constexpr bool hasFlag(ChangeFlag value, ChangeFlag flag) noexcept {
    return (static_cast<std::uint16_t>(value) & static_cast<std::uint16_t>(flag)) != 0;
}

/// Thresholds used to suppress sensor/reconstruction jitter from semantic Reality Diff output.
struct DiffPolicy final {
    float translationMeters{0.01F};
    float rotationRadians{0.01F};
    float relativeScale{0.01F};
    float boundsMeters{0.01F};
    float confidenceDelta{0.05F};
};

struct EntityDelta final {
    EntityId id{};
    ChangeFlag flags{ChangeFlag::none};
    float translationMeters{};
    float rotationRadians{};
    float relativeScale{};
    float boundsMeters{};
    float confidenceDelta{};
};

struct WorldDiffSummary final {
    std::size_t added{};
    std::size_t removed{};
    std::size_t modified{};
    std::size_t unchanged{};
    float changeRatio{};
};

/// Git-style difference between two persistent world revisions.
struct WorldDiff final {
    std::uint64_t beforeRevision{};
    std::uint64_t afterRevision{};
    TimestampNs beforeTimestamp{};
    TimestampNs afterTimestamp{};
    std::vector<EntityDelta> entities;
    WorldDiffSummary summary;
};

[[nodiscard]] Result<void> validateSnapshot(const WorldSnapshot& snapshot);
[[nodiscard]] Result<WorldDiff> diffSnapshots(const WorldSnapshot& before,
                                              const WorldSnapshot& after,
                                              DiffPolicy policy = {});

/// Append-only temporal memory for a captured world.
///
/// The timeline deliberately owns immutable snapshots rather than mutating the latest scene in
/// place. That makes temporal comparison, rollback, auditability, collaboration and future
/// selective re-optimization deterministic by construction.
class WorldTimeline final {
  public:
    [[nodiscard]] Result<std::uint64_t> append(WorldSnapshot snapshot);
    [[nodiscard]] Result<const WorldSnapshot*> snapshot(std::uint64_t revision) const;
    [[nodiscard]] Result<WorldDiff> diff(std::uint64_t beforeRevision,
                                         std::uint64_t afterRevision,
                                         DiffPolicy policy = {}) const;
    [[nodiscard]] Result<WorldDiff> latestDiff(DiffPolicy policy = {}) const;

    [[nodiscard]] std::size_t size() const noexcept {
        return snapshots_.size();
    }

    [[nodiscard]] bool empty() const noexcept {
        return snapshots_.empty();
    }

    [[nodiscard]] const WorldSnapshot* latest() const noexcept {
        return snapshots_.empty() ? nullptr : &snapshots_.back();
    }

    /// Read-only chronological access used by persistence, diagnostics, Studio history and sync.
    [[nodiscard]] const std::vector<WorldSnapshot>& snapshots() const noexcept {
        return snapshots_;
    }

  private:
    std::vector<WorldSnapshot> snapshots_;
};

} // namespace aether::world
