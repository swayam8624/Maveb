#include <aether/world/WorldModel.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::ChangeFlag;
using aether::world::EntityPatch;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world::hasFlag;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState observation(std::string name, std::string semantic, float x) {
    EntityState result;
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F},
                                {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = 10;
    result.appearanceSignature = 20;
    return result;
}

const EntityState* findByName(const PersistentWorldModel& model, const std::string& name) {
    const auto* latest = model.latest();
    if (!latest)
        return nullptr;
    for (const EntityState& entity : latest->entities) {
        if (entity.name == name)
            return &entity;
    }
    return nullptr;
}

void testTranslationEditMovesBoundsAndCreatesRealityDiff() {
    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk", "desk", 0.0F),
                              observation("Chair", "chair", 2.0F)})
               .has_value(),
           "edit fixture must initialize persistent world");
    const EntityState* desk = findByName(model, "Desk");
    expect(desk != nullptr, "desk must exist before authored edit");
    if (!desk)
        return;

    EntityPatch patch;
    patch.id = desk->id;
    auto moved = desk->transform;
    moved.translation.x = 1.0F;
    patch.transform = moved;

    const std::uint64_t allocatorBefore = model.nextEntityId();
    const auto edit = model.edit(200, {patch});
    expect(edit.has_value(), "translation-only authored edit must commit");
    if (!edit)
        return;
    expect(edit->candidate.revision == 2, "authored edit must create the next world revision");
    expect(edit->updatedEntities == 1 && edit->removedEntities == 0,
           "translation edit must update exactly one entity");
    expect(edit->diff.summary.modified == 1,
           "translation edit must appear as one modified persistent entity");
    expect(!edit->diff.entities.empty() &&
               hasFlag(edit->diff.entities.front().flags, ChangeFlag::translated),
           "translation edit must carry translated Reality Diff flag");
    expect(!edit->selectiveUpdate.dirtyRegions.empty(),
           "translation edit must schedule bounded local reconstruction work");
    expect(model.nextEntityId() == allocatorBefore,
           "authored edit must not consume new persistent entity identity");

    const EntityState* movedDesk = findByName(model, "Desk");
    expect(movedDesk && movedDesk->transform.translation.x == 1.0F,
           "committed world must contain authored desk transform");
    expect(movedDesk && movedDesk->worldBounds.minimum.x == 0.75F &&
               movedDesk->worldBounds.maximum.x == 1.25F,
           "translation-only edit must translate previous world bounds automatically");
}

void testRemovalAndSemanticEdit() {
    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk", "object", 0.0F),
                              observation("Chair", "chair", 2.0F)})
               .has_value(),
           "removal fixture must initialize world");
    const EntityState* desk = findByName(model, "Desk");
    const EntityState* chair = findByName(model, "Chair");
    if (!desk || !chair) {
        expect(false, "edit fixture entities must exist");
        return;
    }

    EntityPatch semantic;
    semantic.id = desk->id;
    semantic.semanticLabel = "desk";
    const auto semanticEdit = model.edit(200, {semantic});
    expect(semanticEdit.has_value(), "semantic relabel must commit as world history");
    if (semanticEdit) {
        expect(semanticEdit->diff.summary.modified == 1,
               "semantic relabel must be represented in Reality Diff");
        expect(semanticEdit->selectiveUpdate.dirtyRegions.empty(),
               "semantic-only edit must not trigger geometry work by default");
    }

    EntityPatch remove;
    remove.id = chair->id;
    remove.remove = true;
    const auto removal = model.edit(300, {remove});
    expect(removal.has_value(), "stable captured entity must support authored removal");
    if (removal) {
        expect(removal->removedEntities == 1, "removal edit must report one removed entity");
        expect(removal->diff.summary.removed == 1,
               "removed captured entity must appear in Reality Diff");
        expect(!removal->selectiveUpdate.dirtyRegions.empty(),
               "removal must dirty the entity's previous spatial extent");
    }
    expect(findByName(model, "Chair") == nullptr,
           "removed captured entity must not exist in committed latest revision");
}

void testRotationRequiresReplacementBoundsAndRollsBack() {
    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk", "desk", 0.0F)}).has_value(),
           "rotation fixture must initialize world");
    const EntityState* desk = findByName(model, "Desk");
    if (!desk) {
        expect(false, "rotation fixture desk must exist");
        return;
    }

    EntityPatch invalid;
    invalid.id = desk->id;
    auto rotated = desk->transform;
    rotated.rotation = simd_quaternion(0.5F, simd_float3{0.0F, 1.0F, 0.0F});
    invalid.transform = rotated;

    const auto rejected = model.edit(200, {invalid});
    expect(!rejected.has_value(),
           "rotation without source-geometry-derived replacement bounds must fail closed");
    expect(model.timeline().size() == 1,
           "rejected authored edit must not append a partial world revision");
}

} // namespace

int main() noexcept {
    try {
        testTranslationEditMovesBoundsAndCreatesRealityDiff();
        testRemovalAndSemanticEdit();
        testRotationRequiresReplacementBoundsAndRollsBack();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Persistent world edit tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
