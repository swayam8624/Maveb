#include <aether/world/SemanticSceneGraph.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::SceneGraphPolicy;
using aether::world::SceneRelationKind;
using aether::world::SemanticSceneGraph;
using aether::world::WorldSnapshot;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState entity(std::uint64_t id, std::string label, Bounds bounds) {
    EntityState result;
    result.id = EntityId{id};
    result.name = label + '-' + std::to_string(id);
    result.semanticLabel = std::move(label);
    result.worldBounds = bounds;
    result.lastObserved = 100;
    return result;
}

bool hasEdge(const SemanticSceneGraph& graph, std::uint64_t source, std::uint64_t target,
             SceneRelationKind kind) {
    for (const auto& edge : graph.edges()) {
        if (edge.source.value == source && edge.target.value == target && edge.kind == kind)
            return true;
    }
    return false;
}

void testImmediateContainmentAndSemanticIndex() {
    WorldSnapshot snapshot;
    snapshot.revision = 4;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(1, "room", Bounds{{-5.0F, -3.0F, -5.0F}, {5.0F, 3.0F, 5.0F}}),
        entity(2, "cabinet", Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}}),
        entity(3, "cup", Bounds{{-0.2F, -0.2F, -0.2F}, {0.2F, 0.2F, 0.2F}}),
        entity(4, "chair", Bounds{{2.0F, -0.5F, 0.0F}, {3.0F, 0.5F, 1.0F}}),
        entity(5, "chair", Bounds{{-4.0F, -0.5F, 0.0F}, {-3.0F, 0.5F, 1.0F}}),
    };

    const auto graph = SemanticSceneGraph::build(snapshot);
    expect(graph.has_value(), "valid persistent revision must build semantic scene graph");
    if (!graph)
        return;

    expect(graph->revision() == 4, "scene graph must preserve source world revision identity");
    const auto* cabinet = graph->node(EntityId{2});
    const auto* cup = graph->node(EntityId{3});
    expect(cabinet && cabinet->parent.value == 1,
           "cabinet must choose room as its immediate containing parent");
    expect(cup && cup->parent.value == 2,
           "cup must choose smallest strict container instead of transitive room parent");
    expect(hasEdge(*graph, 1, 2, SceneRelationKind::contains),
           "scene graph must emit direct room-to-cabinet containment edge");
    expect(hasEdge(*graph, 2, 3, SceneRelationKind::contains),
           "scene graph must emit direct cabinet-to-cup containment edge");
    expect(!hasEdge(*graph, 1, 3, SceneRelationKind::contains),
           "scene graph must not emit redundant transitive containment edge");

    const auto chairs = graph->semantic("chair");
    expect(chairs.size() == 2 && chairs[0].value == 4 && chairs[1].value == 5,
           "semantic graph lookup must return stable IDs in deterministic order");
}

void testIntersectionAndNearRelations() {
    WorldSnapshot snapshot;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(10, "box", Bounds{{0.0F, 0.0F, 0.0F}, {1.0F, 1.0F, 1.0F}}),
        entity(11, "box", Bounds{{0.5F, 0.0F, 0.0F}, {1.5F, 1.0F, 1.0F}}),
        entity(12, "box", Bounds{{2.0F, 0.0F, 0.0F}, {3.0F, 1.0F, 1.0F}}),
        entity(13, "box", Bounds{{5.0F, 0.0F, 0.0F}, {6.0F, 1.0F, 1.0F}}),
    };

    SceneGraphPolicy policy;
    policy.nearDistanceMeters = 0.75F;
    const auto graph = SemanticSceneGraph::build(snapshot, policy);
    expect(graph.has_value(), "intersection/near fixture must build scene graph");
    if (!graph)
        return;

    expect(hasEdge(*graph, 10, 11, SceneRelationKind::intersects),
           "overlapping AABBs must produce intersection relation");
    expect(hasEdge(*graph, 11, 12, SceneRelationKind::near),
           "separated surfaces inside near threshold must produce near relation");
    expect(!hasEdge(*graph, 12, 13, SceneRelationKind::near),
           "entities outside near threshold must not receive a near edge");
}

void testCandidateBudgetFailsClosed() {
    WorldSnapshot snapshot;
    snapshot.timestamp = 100;
    snapshot.entities = {
        entity(20, "dense", Bounds{{0.0F, 0.0F, 0.0F}, {1.0F, 1.0F, 1.0F}}),
        entity(21, "dense", Bounds{{0.1F, 0.0F, 0.0F}, {1.1F, 1.0F, 1.0F}}),
        entity(22, "dense", Bounds{{0.2F, 0.0F, 0.0F}, {1.2F, 1.0F, 1.0F}}),
    };
    SceneGraphPolicy policy;
    policy.maximumCandidatePairs = 1;
    const auto rejected = SemanticSceneGraph::build(snapshot, policy);
    expect(!rejected.has_value(), "scene graph must fail closed when candidate budget is exceeded");
}

} // namespace

int main() noexcept {
    try {
        testImmediateContainmentAndSemanticIndex();
        testIntersectionAndNearRelations();
        testCandidateBudgetFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Semantic scene graph tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
