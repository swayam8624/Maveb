#include <aether/world/RevisionCertificate.hpp>

#include <array>
#include <cmath>
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

void testAnalyticChainPathSum() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.2, "g01"},
        RevisionDependency{1, 2, RevisionDependencyClass::analytic, 0.2, "g12"},
    };
    auto graph = RevisionGraph::build(3, dependencies);
    expect(graph.has_value(), "chain graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sourceNodes{0};
    const std::array<double, 3> source{1.0, 0.0, 0.0};
    const std::array<double, 3> change{1.0, 0.2, 0.04};
    const std::array<std::size_t, 1> cone{0};
    const std::array<double, 3> work{1.0, 1.0, 1.0};
    RevisionQoIContract qoi{
        .name = "tail",
        .nodeWeights = {0.0, 0.0, 1.0},
        .epsilon = 0.05,
    };

    auto cert = certifyRevisionConeDAG(
        *graph, sourceNodes, source, change, cone, work,
        std::span<const RevisionQoIContract>(&qoi, 1));
    expect(cert.has_value(), "chain certificate must execute");
    if (!cert)
        return;
    expect(cert->stable && cert->passes,
           "chain certificate must pass its declared tolerance");
    expect(cert->qoiBounds.size() == 1 &&
               std::abs(cert->qoiBounds[0].certifiedBound - 0.04) < 1.0e-12,
           "chain path sum must equal 0.2 * 0.2");
}

void testBranchingPathSumsAccumulate() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.3, "a"},
        RevisionDependency{0, 2, RevisionDependencyClass::analytic, 0.4, "b"},
        RevisionDependency{1, 3, RevisionDependencyClass::analytic, 0.5, "c"},
        RevisionDependency{2, 3, RevisionDependencyClass::analytic, 0.25, "d"},
    };
    auto graph = RevisionGraph::build(4, dependencies);
    expect(graph.has_value(), "branching graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sourceNodes{0};
    const std::array<double, 4> source{1.0, 0.0, 0.0, 0.0};
    const std::array<double, 4> change{1.0, 0.3, 0.4, 0.25};
    const std::array<std::size_t, 1> cone{0};
    const std::array<double, 4> work{1.0, 1.0, 1.0, 1.0};
    RevisionQoIContract qoi{
        .name = "sink",
        .nodeWeights = {0.0, 0.0, 0.0, 1.0},
        .epsilon = 0.3,
    };

    auto cert = certifyRevisionConeDAG(
        *graph, sourceNodes, source, change, cone, work,
        std::span<const RevisionQoIContract>(&qoi, 1));
    expect(cert && cert->stable, "branching DAG must certify");
    if (!cert)
        return;
    const double expected = 0.3 * 0.5 + 0.4 * 0.25;
    expect(std::abs(cert->qoiBounds[0].certifiedBound - expected) < 1.0e-12,
           "parallel analytic paths must add conservatively");
}

void testSoftToHardBoundaryRejectsTooSmallCone() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.2, "soft"},
        RevisionDependency{1, 2, RevisionDependencyClass::hard, std::nullopt, ""},
    };
    auto graph = RevisionGraph::build(3, dependencies);
    expect(graph.has_value(), "soft-to-hard graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sourceNodes{0};
    const std::array<double, 3> source{1.0, 0.0, 0.0};
    const std::array<double, 3> change{1.0, 0.2, 0.2};
    const std::array<std::size_t, 1> cone{0};
    const std::array<double, 3> work{1.0, 1.0, 1.0};
    RevisionQoIContract qoi{
        .name = "state",
        .nodeWeights = {0.0, 0.0, 1.0},
        .epsilon = 1.0,
    };

    auto cert = certifyRevisionConeDAG(
        *graph, sourceNodes, source, change, cone, work,
        std::span<const RevisionQoIContract>(&qoi, 1));
    expect(cert && !cert->stable,
           "cone that excludes required soft-to-hard exact state must be rejected");
}

void testCyclicExteriorFailsClosed() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.2, "a"},
        RevisionDependency{1, 2, RevisionDependencyClass::analytic, 0.2, "b"},
        RevisionDependency{2, 1, RevisionDependencyClass::analytic, 0.2, "c"},
    };
    auto graph = RevisionGraph::build(3, dependencies);
    expect(graph.has_value(), "cyclic analytic graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sourceNodes{0};
    const std::array<double, 3> source{1.0, 0.0, 0.0};
    const std::array<double, 3> change{1.0, 0.25, 0.25};
    const std::array<std::size_t, 1> cone{0};
    const std::array<double, 3> work{1.0, 1.0, 1.0};
    RevisionQoIContract qoi{
        .name = "state",
        .nodeWeights = {0.0, 1.0, 1.0},
        .epsilon = 1.0,
    };

    auto cert = certifyRevisionConeDAG(
        *graph, sourceNodes, source, change, cone, work,
        std::span<const RevisionQoIContract>(&qoi, 1));
    expect(cert && !cert->stable,
           "cyclic exterior must fail closed instead of pretending DAG certification");
}

void testFullRebuildHasZeroResidual() {
    using namespace aether::world;
    const std::array dependencies{
        RevisionDependency{0, 1, RevisionDependencyClass::analytic, 0.5, "a"},
    };
    auto graph = RevisionGraph::build(2, dependencies);
    expect(graph.has_value(), "graph must build");
    if (!graph)
        return;

    const std::array<std::size_t, 1> sourceNodes{0};
    const std::array<double, 2> source{1.0, 0.0};
    const std::array<double, 2> change{1.0, 0.5};
    const std::array<std::size_t, 2> cone{0, 1};
    const std::array<double, 2> work{2.0, 3.0};
    RevisionQoIContract qoi{
        .name = "state",
        .nodeWeights = {1.0, 1.0},
        .epsilon = 0.0,
    };

    auto cert = certifyRevisionConeDAG(
        *graph, sourceNodes, source, change, cone, work,
        std::span<const RevisionQoIContract>(&qoi, 1));
    expect(cert && cert->stable && cert->passes && cert->usedFullRebuild,
           "full rebuild must certify zero stale residual");
    if (cert)
        expect(cert->work == cert->fullWork && cert->qoiBounds[0].certifiedBound == 0.0,
               "full rebuild work and residual must equal full baseline and zero");
}

} // namespace

int main() noexcept {
    try {
        testAnalyticChainPathSum();
        testBranchingPathSumsAccumulate();
        testSoftToHardBoundaryRejectsTooSmallCone();
        testCyclicExteriorFailsClosed();
        testFullRebuildHasZeroResidual();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Revision certificate DAG tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
