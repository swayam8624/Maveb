#pragma once

#include <aether/canonical/CanonicalAsset.hpp>
#include <aether/world/PersistentWorld.hpp>

#include <string>
#include <vector>

namespace aether::world_adapters {

struct CanonicalObservationConfig final {
    std::string semanticLabel{"captured-instance"};
    float fallbackConfidence{1.0F};
};

/// Converts an already validated canonical captured asset into unassigned persistent-world
/// observations. Each canonical mesh instance becomes one persistent entity candidate with:
///
/// - metric world transform and world-space bounds,
/// - deterministic local-geometry and material-appearance signatures,
/// - canonical capture confidence,
/// - `id == 0`, ready for PersistentWorldModel association.
[[nodiscard]] Result<std::vector<world::EntityState>>
observationsFromCanonicalAsset(const canonical::CanonicalAssetPayload& asset,
                               world::TimestampNs timestamp,
                               CanonicalObservationConfig config = {});

} // namespace aether::world_adapters
