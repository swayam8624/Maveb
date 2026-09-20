#include <aether/revision/RevisionPlanner.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>
#include <vector>

namespace {

using namespace aether::revision;
int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

RevisionGraph simpleChain() {
    auto graph = RevisionGraph::build(
        {
            {"gaussian-edit", 1.0, 0.5},
            {"current-image", 2.0, 0.0},
            {"history", 3.0, 0.0},
        },
        {
            {0, 1, RevisionEdgeClass::analytic, 0.4, "gaussian-image-v1"},
            {1, 2, RevisionEdgeClass::analytic, 0.5, "temporal-v1"},
        });
    if (!graph)
        throw std::runtime_error(graph.error().describe());
    return std::move(*graph);
}

void testAnalyticDagCertificate() {
    auto graph = simpleChain();
    const std::vector<double> source{0.0, 0.0, 0.0};
    const std::vector<RevisionNodeId> cone{0};
    const std::vector<RevisionQoI> qois{
        {"resolved-rgb", {{2, 1.0}}, 0.11},
    };
    auto certificate = certifyRevisionCone(graph, source, cone, qois);
    expect(certificate.has_value(), "analytic DAG certificate must succeed");
    if (!certificate)
        return;
    expect(certificate->stable, "analytic DAG response must be stable");
    expect(certificate->passes, "0.5*0.4*0.5 must pass epsilon 0.11");
    expect(std::abs(certificate->qois.front().bound - 0.1) < 1e-12,
           "analytic chain must propagate exact conservative product");
}

void testEmpiricalEdgeFailsClosedAsExactPredecessor() {
    auto graph = RevisionGraph::build(
        {
            {"empirical-source", 1.0, 1.0},
            {"target", 1.0, 0.0},
        },
        {
            {0, 1, RevisionEdgeClass::empirical, 0.1, ""},
        });
    expect(graph.has_value(), "empirical graph must build");
    if (!graph)
        return;
    auto closure = graph->closeExactPredecessors(std::vector<RevisionNodeId>{1});
    expect(closure.has_value() && closure->size() == 2,
           "empirical edge must be promoted to exact predecessor for certification");
}

void testAnalyticCycleFailsClosed() {
    auto graph = RevisionGraph::build(
        {
            {"a", 1.0, 0.5},
            {"b", 1.0, 0.5},
        },
        {
            {0, 1, RevisionEdgeClass::analytic, 0.4, "a-b"},
            {1, 0, RevisionEdgeClass::analytic, 0.4, "b-a"},
        });
    expect(graph.has_value(), "cyclic graph definition must build");
    if (!graph)
        return;

    const std::vector<double> source{0.1, 0.0};
    const std::vector<RevisionNodeId> empty;
    const std::vector<RevisionQoI> qois{{"out", {{1, 1.0}}, 1.0}};
    auto certificate = certifyRevisionCone(*graph, source, empty, qois);
    expect(certificate.has_value(), "cyclic candidate must return fail-closed certificate");
    if (!certificate)
        return;
    expect(!certificate->stable && !certificate->passes,
           "analytic exterior cycle must not be silently certified");
}

void testGreedyExpansionCanAvoidFullRebuild() {
    auto graph = RevisionGraph::build(
        {
            {"edit", 1.0, 1.0},
            {"cheap-coupled", 1.0, 0.5},
            {"expensive-output", 10.0, 0.0},
        },
        {
            {0, 1, RevisionEdgeClass::analytic, 0.8, "edit-coupled"},
            {1, 2, RevisionEdgeClass::analytic, 0.8, "coupled-output"},
        });
    expect(graph.has_value(), "greedy graph must build");
    if (!graph)
        return;
    const std::vector<double> source{0.0, 0.0, 0.0};
    const std::vector<RevisionNodeId> hard{0};
    const std::vector<RevisionQoI> qois{{"out", {{2, 1.0}}, 0.3}};
    auto result = greedyCertifiedRevisionCone(*graph, source, hard, qois);
    expect(result.has_value(), "greedy planner must return a feasible result");
    if (!result)
        return;
    expect(result->passes, "greedy result must certify QoI");
    expect(!result->fullRebuild,
           "greedy planner should repair cheap coupled node rather than full rebuild");
    expect(result->work < result->fullWork,
           "greedy certified cone must save frozen scalar work");
}

void testFullFallbackWhenOnlyOutputRepairCanPass() {
    auto graph = simpleChain();
    const std::vector<double> source{0.0, 0.0, 0.0};
    const std::vector<RevisionNodeId> hard{0};
    const std::vector<RevisionQoI> qois{{"resolved-rgb", {{2, 1.0}}, 0.0}};
    auto result = greedyCertifiedRevisionCone(graph, source, hard, qois);
    expect(result.has_value(), "zero-epsilon planner must return fallback");
    if (!result)
        return;
    expect(result->passes, "full rebuild fallback must always certify zero residual");
    expect(result->fullRebuild,
           "zero epsilon should force full rebuild in this chain");
}

void testInvalidAnalyticEdgeWithoutProvenanceRejected() {
    auto graph = RevisionGraph::build(
        {
            {"a", 1.0, 1.0},
            {"b", 1.0, 0.0},
        },
        {
            {0, 1, RevisionEdgeClass::analytic, 0.5, ""},
        });
    expect(!graph.has_value(),
           "analytic edge without bound provenance must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testAnalyticDagCertificate();
        testEmpiricalEdgeFailsClosedAsExactPredecessor();
        testAnalyticCycleFailsClosed();
        testGreedyExpansionCanAvoidFullRebuild();
        testFullFallbackWhenOnlyOutputRepairCanPass();
        testInvalidAnalyticEdgeWithoutProvenanceRejected();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }
    if (failures == 0)
        std::cout << "CBRC revision planner tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
