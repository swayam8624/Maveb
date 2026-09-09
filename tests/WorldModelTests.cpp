#include <aether/world/WorldModel.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world::WorldIngestPolicy;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState observation(std::string name, std::string semantic, float x,
                        std::uint64_t geometrySignature, std::uint64_t appearanceSignature) {
    EntityState result;
    result.id = EntityId{};
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F},
                                {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = geometrySignature;
    result.appearanceSignature = appearanceSignature;
    return result;
}

const EntityState* findByName(const PersistentWorldModel& model, const std::string& name) {
    const auto* latest = model.latest();
    if (!latest)
        return nullptr;
    for (const EntityState& state : latest->entities) {
        if (state.name == name)
            return &state;
    }
    return nullptr;
}

void testInitialAndIncrementalIngest() {
    PersistentWorldModel model;

    const auto first = model.ingest(
        100, {observation("Wall", "wall", 0.0F, 10, 20),
              observation("Chair", "chair", 1.0F, 30, 40)});
    expect(first.has_value(), "initial observation set must commit as the first world revision");
    if (!first)
        return;

    expect(first->revision == 1, "initial ingest must create revision 1");
    expect(first->createdIds == 2 && first->reusedIds == 0,
           "initial ingest must allocate identities for every observation");
    expect(first->diff.summary.added == 2,
           "initial ingest must appear as additions relative to the empty world");
    expect(first->selectiveUpdate.changedEntities == 2,
           "initial additions must schedule spatial reconstruction work");
    expect(model.timeline().size() == 1, "successful initial ingest must append one snapshot");

    const EntityState* firstWall = findByName(model, "Wall");
    const EntityState* firstChair = findByName(model, "Chair");
    expect(firstWall && firstWall->id.value == 1, "first observed wall must receive stable ID 1");
    expect(firstChair && firstChair->id.value == 2,
           "first observed chair must receive stable ID 2");

    const auto second = model.ingest(
        200, {observation("Wall", "wall", 0.002F, 10, 20),
              observation("Chair", "chair", 1.5F, 30, 41),
              observation("Monitor", "monitor", 3.0F, 50, 60)});
    expect(second.has_value(), "new physical observation must advance persistent world history");
    if (!second)
        return;

    expect(second->revision == 2, "second ingest must create revision 2");
    expect(second->reusedIds == 2 && second->createdIds == 1,
           "known wall/chair must persist while monitor receives a new identity");
    expect(second->diff.summary.added == 1,
           "monitor must be represented as an addition instead of identity churn");
    expect(second->diff.summary.modified == 1,
           "moved/appearance-changed chair must be represented as a modification");
    expect(second->diff.summary.unchanged == 1,
           "sub-threshold wall jitter must remain unchanged");
    expect(model.timeline().size() == 2, "successful incremental ingest must append history");

    const EntityState* wall = findByName(model, "Wall");
    const EntityState* chair = findByName(model, "Chair");
    const EntityState* monitor = findByName(model, "Monitor");
    expect(wall && wall->id.value == 1, "wall identity must survive recapture");
    expect(chair && chair->id.value == 2, "chair identity must survive motion");
    expect(monitor && monitor->id.value == 3, "new monitor must receive the next fresh ID");
}

void testFailedUpdateRollsBackTimelineAndAllocator() {
    PersistentWorldModel model;
    const auto first = model.ingest(100, {observation("Desk", "desk", 0.0F, 1, 1)});
    expect(first.has_value(), "rollback fixture must establish an initial revision");
    if (!first)
        return;

    const std::size_t timelineSizeBefore = model.timeline().size();
    const std::uint64_t allocatorBefore = model.nextEntityId();
    const std::uint64_t revisionBefore = model.latest() ? model.latest()->revision : 0;

    WorldIngestPolicy impossibleBudget;
    impossibleBudget.selectiveUpdate.cellSizeMeters = 0.01F;
    impossibleBudget.selectiveUpdate.haloCells = 2;
    impossibleBudget.selectiveUpdate.maximumDirtyRegions = 1;

    const auto rejected = model.ingest(
        200, {observation("Desk", "desk", 4.0F, 1, 1),
              observation("Lamp", "lamp", 8.0F, 2, 2)},
        impossibleBudget);
    expect(!rejected.has_value(), "dirty-region budget overflow must reject the world transaction");
    expect(model.timeline().size() == timelineSizeBefore,
           "failed transaction must not append a partial world snapshot");
    expect(model.nextEntityId() == allocatorBefore,
           "failed transaction must not consume persistent entity IDs");
    expect(model.latest() && model.latest()->revision == revisionBefore,
           "failed transaction must leave the committed latest revision unchanged");

    const auto recovered = model.ingest(
        300, {observation("Desk", "desk", 0.1F, 1, 1),
              observation("Lamp", "lamp", 3.0F, 2, 2)});
    expect(recovered.has_value(), "valid update after rollback must still commit normally");
    if (!recovered)
        return;
    const EntityState* lamp = findByName(model, "Lamp");
    expect(lamp && lamp->id.value == allocatorBefore,
           "ID rejected by failed transaction must be reusable by the next successful commit");
}

void testTimestampFailureIsNonMutating() {
    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk", "desk", 0.0F, 1, 1)}).has_value(),
           "timestamp fixture must initialize world");
    const std::uint64_t allocator = model.nextEntityId();

    const auto rejected = model.ingest(100, {observation("Desk", "desk", 0.0F, 1, 1)});
    expect(!rejected.has_value(), "non-increasing observation time must be rejected");
    expect(model.timeline().size() == 1, "timestamp rejection must not append history");
    expect(model.nextEntityId() == allocator, "timestamp rejection must not consume identity space");
}

void testHistoricalRevertCreatesNewRevisionWithoutReusingIds() {
    PersistentWorldModel model;
    const auto first = model.ingest(
        100, {observation("Desk", "desk", 0.0F, 10, 10),
              observation("Chair", "chair", 1.0F, 20, 20)});
    expect(first.has_value(), "time-travel fixture must create revision 1");
    if (!first)
        return;

    const auto second = model.ingest(
        200, {observation("Desk", "desk", 0.0F, 10, 10),
              observation("Chair", "chair", 1.5F, 20, 20),
              observation("Plant", "plant", 3.0F, 30, 30)});
    expect(second.has_value(), "time-travel fixture must create revision 2");
    if (!second)
        return;

    const EntityState* plantBeforeRevert = findByName(model, "Plant");
    expect(plantBeforeRevert && plantBeforeRevert->id.value == 3,
           "future plant must receive stable ID 3 before restore");
    const std::uint64_t allocatorBeforeRevert = model.nextEntityId();
    expect(allocatorBeforeRevert == 4, "future identity allocation must advance before restore");

    const auto reverted = model.revertTo(1, 300);
    expect(reverted.has_value(), "historical world state must restore as a new revision");
    if (!reverted)
        return;

    expect(reverted->revision == 3 && reverted->sourceRevision == 1,
           "restoring revision 1 after revision 2 must append revision 3");
    expect(reverted->diff.summary.removed == 1,
           "restoring the past must remove the future-only plant in Reality Diff");
    expect(reverted->diff.summary.modified == 1,
           "restoring the past must move the chair back as a modification");
    expect(!reverted->selectiveUpdate.dirtyRegions.empty(),
           "time travel must schedule local spatial work for reversed changes");
    expect(model.timeline().size() == 3,
           "time travel must preserve both historical revisions and append a third");
    expect(model.nextEntityId() == allocatorBeforeRevert,
           "time travel must never roll the persistent-ID allocator backward");
    expect(findByName(model, "Plant") == nullptr,
           "latest restored state must no longer contain the future-only plant");

    const EntityState* restoredChair = findByName(model, "Chair");
    expect(restoredChair && restoredChair->id.value == 2,
           "restored historical entity must preserve its stable identity");
    expect(restoredChair && restoredChair->transform.translation.x == 1.0F,
           "restored chair must return to its historical metric position");

    const auto future = model.ingest(
        400, {observation("Desk", "desk", 0.0F, 10, 10),
              observation("Chair", "chair", 1.0F, 20, 20),
              observation("Lamp", "lamp", 5.0F, 40, 40)});
    expect(future.has_value(), "world must continue evolving after time travel");
    if (!future)
        return;
    const EntityState* lamp = findByName(model, "Lamp");
    expect(lamp && lamp->id.value == 4,
           "new future entity must not reuse ID 3 from the reverted-away plant");

    const std::size_t sizeBeforeNoOp = model.timeline().size();
    const auto noOp = model.revertTo(model.latest()->revision, 500);
    expect(!noOp.has_value(), "restoring the already-latest revision must fail as a no-op");
    expect(model.timeline().size() == sizeBeforeNoOp,
           "rejected no-op time travel must not append world history");
}

} // namespace

int main() noexcept {
    try {
        testInitialAndIncrementalIngest();
        testFailedUpdateRollsBackTimelineAndAllocator();
        testTimestampFailureIsNonMutating();
        testHistoricalRevertCreatesNewRevisionWithoutReusingIds();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Persistent world model tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
