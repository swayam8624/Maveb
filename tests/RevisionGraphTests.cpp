#include <aether/world/RevisionGraph.hpp>

#include <array>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <vector>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testHardForwardClosureStopsAtAnalyticEdge() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::hard, std::nullopt, ""},
        RevisionDependency{1, 2, RevisionDependencyClass::empirical, 0.25, "predictor-v1"},
        RevisionDependency{2, 3, RevisionDependencyClass::analytic, 0.20, "proof-v1"},
    };
    auto graph = RevisionGraph::build(4, dependencies);
    expect(graph.has_value(), "typed revision graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> source{0};
    auto closure = graph->hardForwardClosure(source);
    expect(closure.has_value(), "hard forward closure must succeed");
    if (!closure)
        return;
    expect(*closure == std::vector<std::size_t>({0, 1, 2}),
           "HARD and EMPIRICAL dependencies must propagate exact repair, ANALYTIC must not");
}

void testChangedAnalyticPredecessorIsRequired() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.25, "proof-v1"},
    };
    auto graph = RevisionGraph::build(2, dependencies);
    expect(graph.has_value(), "analytic revision graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> seed{1};
    const std::array<double, 2> changed{1.0, 0.25};
    auto closure = graph->activePredecessorClosure(seed, changed);
    expect(closure.has_value(), "active predecessor closure must succeed");
    if (!closure)
        return;
    expect(*closure == std::vector<std::size_t>({0, 1}),
           "changed analytic predecessor must be pulled into repair cone");
}

void testUnchangedAnalyticPredecessorCanRemainOutside() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.25, "proof-v1"},
    };
    auto graph = RevisionGraph::build(2, dependencies);
    expect(graph.has_value(), "analytic revision graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> cone{1};
    const std::array<double, 2> changed{0.0, 1.0};
    auto consistent = graph->isActivePredecessorConsistent(cone, changed);
    expect(consistent.has_value() && *consistent,
           "unchanged predecessor must not be repaired merely because it is read");
}

void testSoftToHardBoundaryForcesRepair() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.25, "proof-v1"},
        RevisionDependency{1, 2, RevisionDependencyClass::hard, std::nullopt, ""},
    };
    auto graph = RevisionGraph::build(3, dependencies);
    expect(graph.has_value(), "soft-to-hard graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sources{0};
    const std::array<double, 3> changed{1.0, 0.25, 0.25};
    auto closure = graph->requiredRepairClosure(sources, changed);
    expect(closure.has_value(), "required repair closure must succeed");
    if (!closure)
        return;
    expect(*closure == std::vector<std::size_t>({0, 1, 2}),
           "active soft-to-hard boundary must force exact successor and changed predecessor");
}

void testZeroChangeHardTargetCanRemainOutside() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.25, "proof-v1"},
        RevisionDependency{1, 2, RevisionDependencyClass::hard, std::nullopt, ""},
    };
    auto graph = RevisionGraph::build(3, dependencies);
    expect(graph.has_value(), "soft-to-hard graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sources{0};
    const std::array<double, 3> changed{1.0, 0.25, 0.0};
    auto closure = graph->requiredRepairClosure(sources, changed);
    expect(closure.has_value() &&
               *closure == std::vector<std::size_t>({0}),
           "exact target with zero true change must not be forced into repair");
}

void testCyclesTerminate() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::hard, std::nullopt, ""},
        RevisionDependency{1, 0, RevisionDependencyClass::hard, std::nullopt, ""},
    };
    auto graph = RevisionGraph::build(2, dependencies);
    expect(graph.has_value(), "cyclic hard graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> source{0};
    auto closure = graph->hardForwardClosure(source);
    expect(closure.has_value() &&
               *closure == std::vector<std::size_t>({0, 1}),
           "hard cycle closure must terminate and include both nodes");
}

void testInvalidAnalyticDependencyFailsClosed() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.2, ""},
    };
    expect(!RevisionGraph::build(2, dependencies),
           "analytic dependency without bound provenance must fail closed");
}

void testOutOfRangeEndpointFailsClosed() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 2, RevisionDependencyClass::hard, std::nullopt, ""},
    };
    expect(!RevisionGraph::build(2, dependencies),
           "out-of-range revision dependency must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testHardForwardClosureStopsAtAnalyticEdge();
        testChangedAnalyticPredecessorIsRequired();
        testUnchangedAnalyticPredecessorCanRemainOutside();
        testSoftToHardBoundaryForcesRepair();
        testZeroChangeHardTargetCanRemainOutside();
        testCyclesTerminate();
        testInvalidAnalyticDependencyFailsClosed();
        testOutOfRangeEndpointFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Revision graph tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
