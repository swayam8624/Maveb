#include <aether/world/PersistentWorld.hpp>
#include <aether/world/SelectiveUpdate.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::ChangeFlag;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::hasFlag;
using aether::world::RegionKey;
using aether::world::RepresentationKind;
using aether::world::SelectiveUpdatePolicy;
using aether::world::WorldSnapshot;
using aether::world::WorldTimeline;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState entity(std::uint64_t id, std::string name, std::string semantic, float x,
                   std::uint64_t geometrySignature, std::uint64_t appearanceSignature,
                   std::uint64_t observedAt) {
    EntityState result;
    result.id = EntityId{id};
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F}, {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = geometrySignature;
    result.appearanceSignature = appearanceSignature;
    result.lastObserved = observedAt;
    return result;
}

const aether::world::EntityDelta* findDelta(const aether::world::WorldDiff& diff,
                                            std::uint64_t id) {
    for (const auto& delta : diff.entities) {
        if (delta.id.value == id)
            return &delta;
    }
    return nullptr;
}

bool containsRegion(const aether::world::SelectiveUpdatePlan& plan, RegionKey key) {
    for (const auto& region : plan.dirtyRegions) {
        if (region.key == key)
            return true;
    }
    return false;
}

void testRealityDiff() {
    WorldTimeline timeline;

    WorldSnapshot first;
    first.timestamp = 100;
    first.entities = {
        entity(1, "Wall", "wall", 0.0F, 10, 20, 100),
        entity(2, "Chair", "chair", 1.0F, 30, 40, 100),
        entity(3, "Cup", "cup", 2.0F, 50, 60, 100),
    };

    WorldSnapshot second;
    second.timestamp = 200;
    second.entities = {
        entity(1, "Wall", "wall", 0.0F, 10, 20, 200),
        entity(2, "Chair", "chair", 1.5F, 30, 41, 200),
        entity(4, "Monitor", "monitor", 3.0F, 70, 80, 200),
    };

    const auto firstRevision = timeline.append(std::move(first));
    const auto secondRevision = timeline.append(std::move(second));
    expect(firstRevision.has_value() && *firstRevision == 1,
           "first snapshot must become revision 1");
    expect(secondRevision.has_value() && *secondRevision == 2,
           "second snapshot must become revision 2");

    const auto diff = timeline.latestDiff();
    expect(diff.has_value(), "two revisions must produce a Reality Diff");
    if (!diff)
        return;

    expect(diff->summary.added == 1, "monitor must be classified as added");
    expect(diff->summary.removed == 1, "cup must be classified as removed");
    expect(diff->summary.modified == 1, "chair must be classified as modified");
    expect(diff->summary.unchanged == 1, "wall must remain unchanged");
    expect(std::abs(diff->summary.changeRatio - 0.75F) < 1.0e-6F,
           "three of four persistent IDs must count as changed");

    const auto* wall = findDelta(*diff, 1);
    const auto* chair = findDelta(*diff, 2);
    const auto* cup = findDelta(*diff, 3);
    const auto* monitor = findDelta(*diff, 4);
    expect(wall && wall->flags == ChangeFlag::none, "stable wall must have no change flags");
    expect(chair && hasFlag(chair->flags, ChangeFlag::translated),
           "chair translation must be reported");
    expect(chair && hasFlag(chair->flags, ChangeFlag::appearance),
           "chair appearance revision must be reported");
    expect(chair && hasFlag(chair->flags, ChangeFlag::bounds),
           "chair world-bounds movement must be reported");
    expect(cup && hasFlag(cup->flags, ChangeFlag::removed), "cup must carry removed flag");
    expect(monitor && hasFlag(monitor->flags, ChangeFlag::added), "monitor must carry added flag");
}

void testSelectiveUpdatePlan() {
    WorldSnapshot before;
    before.revision = 1;
    before.timestamp = 100;
    before.entities = {entity(1, "Wall", "wall", 0.0F, 10, 20, 100),
                       entity(2, "Chair", "chair", 1.0F, 30, 40, 100)};

    WorldSnapshot after;
    after.revision = 2;
    after.timestamp = 200;
    after.entities = {entity(1, "Wall", "wall", 0.0F, 10, 20, 200),
                      entity(2, "Chair", "chair", 1.5F, 30, 41, 200),
                      entity(3, "Monitor", "monitor", 3.0F, 50, 60, 200)};

    const auto diff = aether::world::diffSnapshots(before, after);
    expect(diff.has_value(), "selective update fixture must produce a Reality Diff");
    if (!diff)
        return;

    SelectiveUpdatePolicy policy;
    policy.cellSizeMeters = 0.5F;
    policy.haloCells = 0;
    const auto plan = aether::world::planSelectiveUpdates(before, after, *diff, policy);
    expect(plan.has_value(), "changed world must produce a selective update plan");
    if (!plan)
        return;

    expect(plan->changedEntities == 2, "moved chair and added monitor must schedule local work");
    expect(plan->unchangedEntities == 1, "unchanged wall must not schedule reconstruction");
    expect(!plan->dirtyRegions.empty(), "spatial changes must dirty metric grid regions");
    expect(containsRegion(*plan, RegionKey{1, -1, -1}),
           "chair previous metric extent must remain in dirty union");
    expect(containsRegion(*plan, RegionKey{3, -1, -1}),
           "chair new metric extent must be included in dirty union");
    expect(containsRegion(*plan, RegionKey{5, -1, -1}),
           "added monitor metric extent must be scheduled");

    for (std::size_t index = 1; index < plan->dirtyRegions.size(); ++index) {
        expect(plan->dirtyRegions[index - 1].key < plan->dirtyRegions[index].key,
               "dirty regions must be unique and deterministically sorted");
    }
}

void testJitterSuppression() {
    WorldSnapshot before;
    before.timestamp = 100;
    before.entities = {entity(10, "Desk", "desk", 1.0F, 1, 2, 100)};

    WorldSnapshot after;
    after.timestamp = 200;
    after.entities = {entity(10, "Desk", "desk", 1.005F, 1, 2, 200)};

    const auto diff = aether::world::diffSnapshots(before, after);
    expect(diff.has_value(), "small sensor jitter must remain diffable");
    if (diff)
        expect(diff->summary.unchanged == 1,
               "default one-centimeter policy must suppress five-millimeter jitter");
}

void testTimelineGuards() {
    WorldTimeline timeline;

    WorldSnapshot valid;
    valid.timestamp = 100;
    valid.entities = {entity(20, "Desk", "desk", 0.0F, 1, 1, 100)};
    expect(timeline.append(valid).has_value(), "valid snapshot must append");

    WorldSnapshot nonMonotonic = valid;
    nonMonotonic.timestamp = 100;
    expect(!timeline.append(nonMonotonic).has_value(),
           "timeline must reject non-increasing timestamps");

    WorldSnapshot duplicate;
    duplicate.timestamp = 200;
    duplicate.entities = {entity(21, "A", "object", 0.0F, 1, 1, 200),
                          entity(21, "B", "object", 1.0F, 2, 2, 200)};
    expect(!timeline.append(duplicate).has_value(), "snapshot must reject duplicate stable IDs");

    WorldSnapshot invalidConfidence;
    invalidConfidence.timestamp = 200;
    auto badEntity = entity(22, "Bad", "object", 0.0F, 1, 1, 200);
    badEntity.confidence = 1.5F;
    invalidConfidence.entities = {badEntity};
    expect(!timeline.append(invalidConfidence).has_value(),
           "snapshot must reject confidence outside [0, 1]");

    expect(!timeline.latestDiff().has_value(), "single-revision timeline must reject latest diff");
}

} // namespace

int main() noexcept {
    try {
        testRealityDiff();
        testSelectiveUpdatePlan();
        testJitterSuppression();
        testTimelineGuards();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Persistent world tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
