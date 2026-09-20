#include <aether/revision/RevisionPlanner.hpp>

#include <algorithm>
#include <cmath>
#include <deque>
#include <limits>
#include <numeric>
#include <utility>

namespace aether::revision {
namespace {

[[nodiscard]] bool finiteNonNegative(double value) noexcept {
    return std::isfinite(value) && value >= 0.0;
}

[[nodiscard]] Result<void> validateQoIs(std::span<const RevisionQoI> qois, std::size_t nodeCount) {
    for (const RevisionQoI& qoi : qois) {
        if (qoi.name.empty() || !finiteNonNegative(qoi.epsilon))
            return fail(ErrorCode::invalidArgument,
                        "Revision QoI requires a name and finite non-negative epsilon");
        for (const RevisionQoITerm& term : qoi.terms) {
            if (term.node >= nodeCount || !finiteNonNegative(term.weight)) {
                return fail(ErrorCode::invalidArgument, "Revision QoI term is invalid", qoi.name);
            }
        }
    }
    return {};
}

[[nodiscard]] double totalWork(const RevisionGraph& graph) noexcept {
    return graph.fullWorkBaseline();
}

[[nodiscard]] double violationScore(const RevisionConeCertificate& certificate) {
    if (!certificate.stable)
        return std::numeric_limits<double>::infinity();
    double score{};
    for (const RevisionQoIResult& qoi : certificate.qois) {
        const double denominator = std::max(qoi.epsilon, 1.0e-15);
        score = std::max(score, qoi.bound / denominator);
    }
    return score;
}

} // namespace

Result<RevisionGraph> RevisionGraph::build(std::vector<RevisionNode> nodes,
                                           std::vector<RevisionEdge> edges,
                                           std::optional<double> fullWorkBaseline) {
    if (nodes.empty())
        return fail(ErrorCode::invalidArgument, "Revision graph requires at least one node");
    if (nodes.size() > static_cast<std::size_t>(std::numeric_limits<RevisionNodeId>::max())) {
        return fail(ErrorCode::resourceExhausted, "Revision graph exceeds uint32 node space");
    }

    for (const RevisionNode& node : nodes) {
        if (!finiteNonNegative(node.workCost) || !finiteNonNegative(node.changeBound)) {
            return fail(ErrorCode::invalidArgument,
                        "Revision node work/change bounds must be finite and non-negative",
                        node.name);
        }
    }

    double summedLocalWork{};
    for (const RevisionNode& node : nodes) {
        summedLocalWork += node.workCost;
        if (!std::isfinite(summedLocalWork))
            return fail(ErrorCode::resourceExhausted, "Revision graph local-work sum overflow");
    }
    const double fullBaseline = fullWorkBaseline.has_value() ? *fullWorkBaseline : summedLocalWork;
    if (!finiteNonNegative(fullBaseline))
        return fail(ErrorCode::invalidArgument,
                    "Revision graph full-work baseline must be finite and non-negative");

    RevisionGraph result;
    result.exactPredecessors_.resize(nodes.size());
    result.analyticOutgoing_.resize(nodes.size());

    for (std::size_t index = 0; index < edges.size(); ++index) {
        const RevisionEdge& edge = edges[index];
        if (edge.source >= nodes.size() || edge.target >= nodes.size())
            return fail(ErrorCode::invalidArgument, "Revision edge endpoint is out of range");
        if (!finiteNonNegative(edge.gain))
            return fail(ErrorCode::invalidArgument,
                        "Revision edge gain must be finite and non-negative");
        if (edge.edgeClass == RevisionEdgeClass::hard) {
            if (edge.gain != 0.0)
                return fail(ErrorCode::invalidArgument,
                            "HARD revision edge must not carry an approximate gain");
            result.exactPredecessors_[edge.target].push_back(edge.source);
        } else if (edge.edgeClass == RevisionEdgeClass::empirical) {
            // EMPIRICAL may order work in future versions, but without an
            // analytic upper bound it is exact for certification.
            result.exactPredecessors_[edge.target].push_back(edge.source);
        } else if (edge.edgeClass == RevisionEdgeClass::analytic) {
            if (edge.boundId.empty())
                return fail(ErrorCode::invalidArgument,
                            "ANALYTIC revision edge requires bound provenance");
            result.analyticOutgoing_[edge.source].push_back(index);
        }
    }

    for (auto& predecessors : result.exactPredecessors_) {
        std::sort(predecessors.begin(), predecessors.end());
        predecessors.erase(std::unique(predecessors.begin(), predecessors.end()),
                           predecessors.end());
    }

    result.nodes_ = std::move(nodes);
    result.edges_ = std::move(edges);
    result.fullWorkBaseline_ = fullBaseline;
    return result;
}

Result<std::vector<RevisionNodeId>>
RevisionGraph::closeExactPredecessors(std::span<const RevisionNodeId> seed) const {
    std::vector<bool> selected(nodes_.size(), false);
    std::vector<RevisionNodeId> stack;
    stack.reserve(seed.size());

    for (const RevisionNodeId id : seed) {
        if (id >= nodes_.size())
            return fail(ErrorCode::invalidArgument, "Revision cone seed node is out of range");
        if (!selected[id]) {
            selected[id] = true;
            stack.push_back(id);
        }
    }

    while (!stack.empty()) {
        const RevisionNodeId target = stack.back();
        stack.pop_back();
        for (const RevisionNodeId predecessor : exactPredecessors_[target]) {
            if (!selected[predecessor]) {
                selected[predecessor] = true;
                stack.push_back(predecessor);
            }
        }
    }

    std::vector<RevisionNodeId> closure;
    for (std::size_t index = 0; index < selected.size(); ++index) {
        if (selected[index])
            closure.push_back(static_cast<RevisionNodeId>(index));
    }
    return closure;
}

Result<RevisionConeCertificate> certifyRevisionCone(const RevisionGraph& graph,
                                                    std::span<const double> sourceBounds,
                                                    std::span<const RevisionNodeId> cone,
                                                    std::span<const RevisionQoI> qois) {
    const std::size_t n = graph.nodeCount();
    if (sourceBounds.size() != n)
        return fail(ErrorCode::invalidArgument,
                    "Revision source-bound vector does not match graph cardinality");
    for (const double bound : sourceBounds) {
        if (!finiteNonNegative(bound))
            return fail(ErrorCode::invalidArgument,
                        "Revision source bounds must be finite and non-negative");
    }
    if (auto valid = validateQoIs(qois, n); !valid)
        return std::unexpected(valid.error());

    auto closed = graph.closeExactPredecessors(cone);
    if (!closed)
        return std::unexpected(closed.error());

    std::vector<RevisionNodeId> sortedCone(cone.begin(), cone.end());
    std::sort(sortedCone.begin(), sortedCone.end());
    sortedCone.erase(std::unique(sortedCone.begin(), sortedCone.end()), sortedCone.end());
    if (*closed != sortedCone) {
        RevisionConeCertificate rejected;
        rejected.cone = std::move(sortedCone);
        rejected.stable = false;
        rejected.passes = false;
        rejected.reason = "cone is not exact-predecessor consistent";
        rejected.fullWork = totalWork(graph);
        for (const RevisionNodeId id : rejected.cone)
            rejected.work += graph.node(id).workCost;
        return rejected;
    }

    std::vector<bool> inside(n, false);
    double work{};
    for (const RevisionNodeId id : sortedCone) {
        inside[id] = true;
        work += graph.node(id).workCost;
    }

    RevisionConeCertificate certificate;
    certificate.cone = sortedCone;
    certificate.work = work;
    certificate.fullWork = totalWork(graph);
    for (std::size_t index = 0; index < n; ++index) {
        if (!inside[index])
            certificate.exterior.push_back(static_cast<RevisionNodeId>(index));
    }

    if (certificate.exterior.empty()) {
        certificate.stable = true;
        certificate.passes = true;
        certificate.fullRebuild = false;
        certificate.reason = "complete repair cone";
        for (const RevisionQoI& qoi : qois)
            certificate.qois.push_back({qoi.name, 0.0, qoi.epsilon});
        return certificate;
    }

    // Sparse analytic DAG response on the unrepaired exterior.
    std::vector<std::size_t> indegree(n, 0);
    std::vector<double> residual(sourceBounds.begin(), sourceBounds.end());
    for (const RevisionNodeId id : certificate.cone)
        residual[id] = 0.0;

    for (const RevisionEdge& edge : graph.edges()) {
        if (edge.edgeClass != RevisionEdgeClass::analytic)
            continue;
        if (inside[edge.source] && !inside[edge.target]) {
            residual[edge.target] += edge.gain * graph.node(edge.source).changeBound;
        } else if (!inside[edge.source] && !inside[edge.target]) {
            ++indegree[edge.target];
        }
        if (!std::isfinite(residual[edge.target]))
            return fail(ErrorCode::resourceExhausted, "Revision residual bound overflow");
    }

    std::deque<RevisionNodeId> ready;
    for (const RevisionNodeId id : certificate.exterior) {
        if (indegree[id] == 0)
            ready.push_back(id);
    }

    std::size_t visited{};
    while (!ready.empty()) {
        const RevisionNodeId source = ready.front();
        ready.pop_front();
        ++visited;

        for (const std::size_t edgeIndex : graph.analyticOutgoing(source)) {
            const RevisionEdge& edge = graph.edges()[edgeIndex];
            if (inside[edge.target])
                continue;
            residual[edge.target] += edge.gain * residual[source];
            if (!std::isfinite(residual[edge.target]))
                return fail(ErrorCode::resourceExhausted,
                            "Revision analytic propagation bound overflow");
            if (--indegree[edge.target] == 0)
                ready.push_back(edge.target);
        }
    }

    if (visited != certificate.exterior.size()) {
        certificate.stable = false;
        certificate.passes = false;
        certificate.reason = "analytic exterior contains a cycle; v1 fails closed";
        for (const RevisionQoI& qoi : qois)
            certificate.qois.push_back(
                {qoi.name, std::numeric_limits<double>::infinity(), qoi.epsilon});
        return certificate;
    }

    certificate.stable = true;
    certificate.reason = "finite sparse analytic DAG response";
    certificate.passes = true;
    for (const RevisionQoI& qoi : qois) {
        double bound{};
        for (const RevisionQoITerm& term : qoi.terms)
            bound += term.weight * residual[term.node];
        if (!std::isfinite(bound))
            return fail(ErrorCode::resourceExhausted, "Revision QoI bound overflow", qoi.name);
        certificate.qois.push_back({qoi.name, bound, qoi.epsilon});
        certificate.passes = certificate.passes && bound <= qoi.epsilon;
    }
    return certificate;
}

Result<RevisionConeCertificate>
greedyCertifiedRevisionCone(const RevisionGraph& graph, std::span<const double> sourceBounds,
                            std::span<const RevisionNodeId> hardClosure,
                            std::span<const RevisionQoI> qois) {
    auto initial = graph.closeExactPredecessors(hardClosure);
    if (!initial)
        return std::unexpected(initial.error());
    std::vector<RevisionNodeId> cone = std::move(*initial);

    auto current = certifyRevisionCone(graph, sourceBounds, cone, qois);
    if (!current)
        return std::unexpected(current.error());
    if (current->passes && current->work < current->fullWork)
        return current;

    const std::size_t n = graph.nodeCount();
    while (cone.size() < n) {
        std::vector<bool> inside(n, false);
        for (const RevisionNodeId id : cone)
            inside[id] = true;

        const double baseScore = violationScore(*current);
        bool found{};
        bool bestPass{};
        double bestUtility = -std::numeric_limits<double>::infinity();
        double bestWork = std::numeric_limits<double>::infinity();
        std::vector<RevisionNodeId> bestCone;
        RevisionConeCertificate bestCertificate;

        for (std::size_t raw = 0; raw < n; ++raw) {
            const auto candidate = static_cast<RevisionNodeId>(raw);
            if (inside[candidate])
                continue;

            std::vector<RevisionNodeId> seed = cone;
            seed.push_back(candidate);
            auto closed = graph.closeExactPredecessors(seed);
            if (!closed)
                return std::unexpected(closed.error());

            double extraWork{};
            for (const RevisionNodeId id : *closed) {
                if (!inside[id])
                    extraWork += graph.node(id).workCost;
            }

            auto tested = certifyRevisionCone(graph, sourceBounds, *closed, qois);
            if (!tested)
                return std::unexpected(tested.error());

            const double nextScore = violationScore(*tested);
            double utility = -std::numeric_limits<double>::infinity();
            if (std::isinf(baseScore) && std::isfinite(nextScore)) {
                utility = std::numeric_limits<double>::infinity();
            } else if (std::isfinite(baseScore) && std::isfinite(nextScore)) {
                const double improvement = baseScore - nextScore;
                utility = extraWork == 0.0
                              ? (improvement > 0.0 ? std::numeric_limits<double>::infinity() : 0.0)
                              : improvement / extraWork;
            }

            const bool passes = tested->passes;
            const bool better =
                !found || (passes && !bestPass) ||
                (passes == bestPass &&
                 (utility > bestUtility || (utility == bestUtility && tested->work < bestWork)));
            if (better) {
                found = true;
                bestPass = passes;
                bestUtility = utility;
                bestWork = tested->work;
                bestCone = std::move(*closed);
                bestCertificate = std::move(*tested);
            }
        }

        if (!found)
            break;
        cone = std::move(bestCone);
        current = std::move(bestCertificate);
        if (current->passes) {
            if (current->work < current->fullWork)
                return current;
            break;
        }
    }

    std::vector<RevisionNodeId> full(n);
    std::iota(full.begin(), full.end(), RevisionNodeId{0});
    auto complete = certifyRevisionCone(graph, sourceBounds, full, qois);
    if (!complete)
        return std::unexpected(complete.error());
    if (complete->work < complete->fullWork)
        return complete;

    complete->work = complete->fullWork;
    complete->fullRebuild = true;
    complete->reason = "full rebuild fallback";
    return complete;
}

} // namespace aether::revision
