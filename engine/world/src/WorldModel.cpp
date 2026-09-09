#include <aether/world/WorldModel.hpp>

#include <limits>

namespace aether::world {

Result<WorldIngestResult> PersistentWorldModel::ingest(TimestampNs timestamp,
                                                        std::vector<EntityState> observations,
                                                        WorldIngestPolicy policy) {
    if (timestamp == 0)
        return fail(ErrorCode::invalidArgument, "Persistent world observation timestamp cannot be zero");

    WorldSnapshot emptyPrevious;
    const WorldSnapshot* previous = timeline_.latest();
    if (!previous)
        previous = &emptyPrevious;

    auto association = associateObservations(*previous, timestamp, std::move(observations),
                                             nextEntityId_, policy.association);
    if (!association)
        return std::unexpected(association.error());

    WorldSnapshot candidate = std::move(association->snapshot);
    if (previous->revision == std::numeric_limits<std::uint64_t>::max())
        return fail(ErrorCode::resourceExhausted, "Persistent world revision space is exhausted");
    candidate.revision = previous->revision + 1U;

    auto diff = diffSnapshots(*previous, candidate, policy.diff);
    if (!diff)
        return std::unexpected(diff.error());

    auto selectiveUpdate =
        planSelectiveUpdates(*previous, candidate, *diff, policy.selectiveUpdate);
    if (!selectiveUpdate)
        return std::unexpected(selectiveUpdate.error());

    auto revision = timeline_.append(candidate);
    if (!revision)
        return std::unexpected(revision.error());
    if (*revision != candidate.revision) {
        return fail(ErrorCode::internal,
                    "Persistent world timeline assigned an unexpected revision during commit");
    }

    nextEntityId_ = association->nextEntityId;
    return WorldIngestResult{
        .revision = *revision,
        .diff = std::move(*diff),
        .selectiveUpdate = std::move(*selectiveUpdate),
        .reusedIds = association->reusedIds,
        .createdIds = association->createdIds,
        .missingPreviousEntities = association->missingPreviousEntities,
    };
}

} // namespace aether::world
