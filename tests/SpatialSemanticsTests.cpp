#include <aether/world/SpatialSemantics.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::RepresentationKind;
using aether::world::SemanticSpatialIndex;
using aether::world::SpatialQueryPolicy;
using aether::world::WorldSnapshot;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState entity(std::uint64_t id, std::string name, std::string semantic, Bounds bounds) {
    EntityState result;
    result.id = EntityId{id};
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = (bounds.minimum + bounds.maximum) * 0.5F;
    result.worldBounds = bounds;
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = id * 10U;
    result.appearanceSignature = id * 100U;
    result.lastObserved = 100;
    return result;
}

WorldSnapshot fixture() {
    WorldSnapshot snapshot;
    snapshot.revision = 9;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(1, "Room", "room", Bounds{{-5.0F, -1.0F, -5.0F}, {5.0F, 3.0F, 5.0F}}),
        entity(2, "Desk", "desk", Bounds{{0.0F, 0.0F, 0.0F}, {2.0F, 1.0F, 1.0F}}),
        entity(3, "Chair Right", "chair", Bounds{{2.2F, 0.0F, 0.0F}, {2.8F, 1.0F, 1.0F}}),
        entity(4, "Chair Left", "chair", Bounds{{-2.0F, 0.0F, 0.0F}, {-1.5F, 1.0F, 1.0F}}),
        entity(5, "Lamp", "lamp", Bounds{{0.5F, 1.1F, 0.2F}, {0.7F, 2.0F, 0.4F}}),
    };
    return snapshot;
}

void testSemanticLookupAndRevisionIdentity() {
    auto index = SemanticSpatialIndex::build(fixture());
    expect(index.has_value(), "valid committed world must build a semantic spatial index");
    if (!index)
        return;

    expect(index->revision() == 9 && index->timestamp() == 100,
           "spatial index must retain the source world revision identity");
    expect(index->size() == 5, "spatial index must contain every persistent entity");

    const auto chairs = index->findSemantic("chair");
    expect(chairs.has_value(), "exact semantic query must succeed");
    if (chairs) {
        expect(chairs->size() == 2, "semantic query must find both chairs");
        expect((*chairs)[0].value == 3 && (*chairs)[1].value == 4,
               "semantic query results must be deterministically sorted by stable ID");
    }

    const auto absent = index->findSemantic("sofa");
    expect(absent.has_value() && absent->empty(),
           "unknown semantic labels must produce an empty successful query");
    expect(!index->findSemantic("").has_value(),
           "empty semantic lookup must be rejected rather than meaning all entities");
}

void testNearestUsesSurfaceDistanceAndFiltering() {
    auto index = SemanticSpatialIndex::build(fixture());
    if (!index) {
        expect(false, "nearest fixture must build index");
        return;
    }

    SpatialQueryPolicy policy;
    policy.maximumDistanceMeters = 10.0F;
    policy.maximumResults = 2;
    const auto hits = index->nearest(simd_float3{2.1F, 0.5F, 0.5F}, "chair", policy);
    expect(hits.has_value(), "semantic nearest query must succeed");
    if (!hits)
        return;

    expect(hits->size() == 2, "nearest semantic query must respect requested result budget");
    expect((*hits)[0].id.value == 3,
           "chair whose AABB surface is ten centimeters away must be the nearest chair");
    expect(std::abs((*hits)[0].pointToBoundsMeters - 0.1F) < 1.0e-5F,
           "nearest query must report point-to-surface distance instead of center-only distance");
    expect((*hits)[0].centerDistanceMeters > (*hits)[0].pointToBoundsMeters,
           "surface and center metrics must remain distinct for spatial reasoning");

    SpatialQueryPolicy tight;
    tight.maximumDistanceMeters = 0.05F;
    const auto none = index->nearest(simd_float3{2.1F, 0.5F, 0.5F}, "chair", tight);
    expect(none.has_value() && none->empty(),
           "maximum metric distance must prune candidates outside the query radius");
}

void testRegionIntersectionAndDeterministicBudget() {
    auto index = SemanticSpatialIndex::build(fixture());
    if (!index) {
        expect(false, "intersection fixture must build index");
        return;
    }

    const Bounds region{{1.9F, -1.0F, -1.0F}, {2.4F, 2.0F, 2.0F}};
    const auto all = index->intersecting(region);
    expect(all.has_value(), "metric region query must succeed");
    if (all) {
        expect(all->size() == 3, "room, desk, and right chair must intersect the query region");
        expect((*all)[0].value == 1 && (*all)[1].value == 2 && (*all)[2].value == 3,
               "intersection results must be deterministically sorted by stable ID");
    }

    const auto one = index->intersecting(region, {}, 2);
    expect(one.has_value() && one->size() == 2 && (*one)[0].value == 1 && (*one)[1].value == 2,
           "intersection budget must truncate after stable-ID sorting");

    const auto chairs = index->intersecting(region, "chair");
    expect(chairs.has_value() && chairs->size() == 1 && chairs->front().value == 3,
           "semantic region query must return only matching intersecting entities");
}

void testContainmentIntersectionAndNearRelations() {
    auto index = SemanticSpatialIndex::build(fixture());
    if (!index) {
        expect(false, "relation fixture must build index");
        return;
    }

    const auto roomDesk = index->relations(EntityId{1}, EntityId{2}, 0.0F);
    expect(roomDesk.has_value(), "room-to-desk relation must be queryable");
    if (roomDesk) {
        expect(roomDesk->intersects, "contained desk must intersect its room bounds");
        expect(roomDesk->subjectContainsReference,
               "room bounds must classify as containing the desk bounds");
        expect(!roomDesk->subjectInsideReference,
               "room must not classify as being inside the smaller desk");
        expect(roomDesk->near && roomDesk->boundsSeparationMeters == 0.0F,
               "intersecting or contained bounds must have zero separation and be near");
    }

    const auto chairDesk = index->relations(EntityId{3}, EntityId{2}, 0.25F);
    expect(chairDesk.has_value(), "chair-to-desk relation must be queryable");
    if (chairDesk) {
        expect(!chairDesk->intersects, "separated chair and desk bounds must not intersect");
        expect(std::abs(chairDesk->boundsSeparationMeters - 0.2F) < 1.0e-5F,
               "relation must compute the metric gap between object surfaces");
        expect(chairDesk->near, "twenty-centimeter surface gap must satisfy 25 cm near threshold");
    }

    const auto chairDeskTight = index->relations(EntityId{3}, EntityId{2}, 0.1F);
    expect(chairDeskTight.has_value() && !chairDeskTight->near,
           "same objects must not be near under a ten-centimeter threshold");
    expect(!index->relations(EntityId{3}, EntityId{3}).has_value(),
           "self-relation must be rejected as semantically meaningless");
    expect(!index->relations(EntityId{999}, EntityId{2}).has_value(),
           "missing stable IDs must fail closed instead of inventing relations");
}

} // namespace

int main() noexcept {
    try {
        testSemanticLookupAndRevisionIdentity();
        testNearestUsesSurfaceDistanceAndFiltering();
        testRegionIntersectionAndDeterministicBudget();
        testContainmentIntersectionAndNearRelations();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Spatial semantic tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
