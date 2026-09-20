#include <aether/world/RevisionCertificate.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <utility>
#include <set>
#include <vector>

namespace aether::world {
namespace {

[[nodiscard]] Result<std::vector<double>>
validatedNonNegative(std::span<const double> values, std::size_t expected,
                     const char* label) {
    if (values.size() != expected) {
        return fail(ErrorCode::invalidArgument,
                    std::string(label) + " count does not match graph node count");
    }
    std::vector<double> result(values.begin(), values.end());
    for (const double value : result) {
        if (!std::isfinite(value) || value < 0.0) {
            return fail(ErrorCode::invalidArgument,
                        std::string(label) + " values must be finite and non-negative");
        }
    }
    return result;
}

[[nodiscard]] Result<std::vector<std::size_t>>
normalizedNodes(std::span<const std::size_t> nodes, std::size_t nodeCount,
                const char* label) {
    std::vector<std::size_t> result(nodes.begin(), nodes.end());
    for (const std::size_t node : result) {
        if (node >= nodeCount) {
            return fail(ErrorCode::invalidArgument,
                        std::string(label) + " contains an out-of-range node");
        }
    }
    std::sort(result.begin(), result.end());
    if (std::adjacent_find(result.begin(), result.end()) != result.end()) {
        return fail(ErrorCode::invalidArgument,
                    std::string(label) + " contains duplicate nodes");
    }
    return result;
}

[[nodiscard]] bool subset(const std::vector<std::size_t>& required,
                          const std::vector<bool>& included) noexcept {
    return std::all_of(required.begin(), required.end(),
                       [&](std::size_t node) { return included[node]; });
}

} // namespace

Result<RevisionConeCertificate>
certifyRevisionConeDAG(const RevisionGraph& graph,
                       std::span<const std::size_t> physicalSources,
                       std::span<const double> sourceBounds,
                       std::span<const double> trueChangeBounds,
                       std::span<const std::size_t> cone,
                       std::span<const double> work,
                       std::span<const RevisionQoIContract> qois) {
    const std::size_t n = graph.nodeCount();
    auto source = validatedNonNegative(sourceBounds, n, "Revision source bound");
    if (!source)
        return std::unexpected(source.error());
    auto change = validatedNonNegative(trueChangeBounds, n, "Revision true-change bound");
    if (!change)
        return std::unexpected(change.error());
    auto nodeWork = validatedNonNegative(work, n, "Revision work");
    if (!nodeWork)
        return std::unexpected(nodeWork.error());
    auto normalizedCone = normalizedNodes(cone, n, "Revision cone");
    if (!normalizedCone)
        return std::unexpected(normalizedCone.error());

    for (const RevisionQoIContract& qoi : qois) {
        if (qoi.name.empty())
            return fail(ErrorCode::invalidArgument, "Revision QoI name cannot be empty");
        if (!std::isfinite(qoi.epsilon) || qoi.epsilon < 0.0)
            return fail(ErrorCode::invalidArgument,
                        "Revision QoI epsilon must be finite and non-negative");
        if (qoi.nodeWeights.size() != n)
            return fail(ErrorCode::invalidArgument,
                        "Revision QoI weight count does not match graph node count");
        for (const double weight : qoi.nodeWeights) {
            if (!std::isfinite(weight) || weight < 0.0)
                return fail(ErrorCode::invalidArgument,
                            "Revision QoI weights must be finite and non-negative");
        }
    }

    std::vector<bool> inCone(n, false);
    for (const std::size_t node : *normalizedCone)
        inCone[node] = true;

    const double fullWork =
        std::accumulate(nodeWork->begin(), nodeWork->end(), 0.0);
    double localWork{};
    for (const std::size_t node : *normalizedCone)
        localWork += (*nodeWork)[node];

    RevisionConeCertificate result;
    result.cone = *normalizedCone;
    result.fullWork = fullWork;
    result.work = localWork;

    if (normalizedCone->size() == n) {
        result.stable = true;
        result.passes = true;
        result.usedFullRebuild = true;
        result.reason = "full rebuild";
        result.exteriorResidualBounds.assign(n, 0.0);
        for (const RevisionQoIContract& qoi : qois)
            result.qoiBounds.push_back({qoi.name, qoi.epsilon, 0.0});
        return result;
    }

    auto required = graph.requiredRepairClosure(physicalSources, *change);
    if (!required)
        return std::unexpected(required.error());
    if (!subset(*required, inCone)) {
        result.stable = false;
        result.passes = false;
        result.reason = "cone does not contain required fail-closed repair set";
        return result;
    }

    auto consistent = graph.isActivePredecessorConsistent(*normalizedCone, *change);
    if (!consistent)
        return std::unexpected(consistent.error());
    if (!*consistent) {
        result.stable = false;
        result.passes = false;
        result.reason = "cone is not active-predecessor consistent";
        return result;
    }

    result.exterior.reserve(n - normalizedCone->size());
    for (std::size_t node = 0; node < n; ++node)
        if (!inCone[node])
            result.exterior.push_back(node);

    std::vector<std::size_t> indegree(n, 0);
    std::vector<std::vector<std::pair<std::size_t, double>>> outgoing(n);
    std::vector<double> residual(n, 0.0);

    for (const std::size_t node : result.exterior)
        residual[node] = (*source)[node];

    for (const RevisionDependency& dependency : graph.dependencies()) {
        if (dependency.dependencyClass != RevisionDependencyClass::analytic)
            continue;
        const double gain = *dependency.gain;
        const bool sourceInside = inCone[dependency.source];
        const bool targetInside = inCone[dependency.target];

        if (sourceInside && !targetInside) {
            residual[dependency.target] += gain * (*change)[dependency.source];
            if (!std::isfinite(residual[dependency.target]))
                return fail(ErrorCode::resourceExhausted,
                            "Revision frontier residual bound overflow");
        } else if (!sourceInside && !targetInside) {
            outgoing[dependency.source].push_back({dependency.target, gain});
            ++indegree[dependency.target];
        }
    }

    std::set<std::size_t> ready;
    for (const std::size_t node : result.exterior)
        if (indegree[node] == 0)
            ready.insert(node);

    std::vector<std::size_t> topological;
    topological.reserve(result.exterior.size());
    while (!ready.empty()) {
        const std::size_t node = *ready.begin();
        ready.erase(ready.begin());
        topological.push_back(node);
        for (const auto& [target, gain] : outgoing[node]) {
            residual[target] += gain * residual[node];
            if (!std::isfinite(residual[target]))
                return fail(ErrorCode::resourceExhausted,
                            "Revision exterior residual bound overflow");
            if (--indegree[target] == 0)
                ready.insert(target);
        }
    }

    if (topological.size() != result.exterior.size()) {
        result.stable = false;
        result.passes = false;
        result.reason =
            "cyclic analytic exterior requires general resolvent or full rebuild";
        return result;
    }

    result.exteriorResidualBounds = residual;
    result.stable = true;
    result.passes = true;
    result.reason = "acyclic analytic exterior certified";

    for (const RevisionQoIContract& qoi : qois) {
        double bound{};
        for (const std::size_t node : result.exterior) {
            bound += qoi.nodeWeights[node] * residual[node];
            if (!std::isfinite(bound))
                return fail(ErrorCode::resourceExhausted,
                            "Revision QoI bound overflow");
        }
        result.qoiBounds.push_back({qoi.name, qoi.epsilon, bound});
        result.passes = result.passes && bound <= qoi.epsilon;
    }

    return result;
}

} // namespace aether::world
