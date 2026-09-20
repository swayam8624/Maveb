#include <aether/world/RevisionGraph.hpp>

#include <algorithm>
#include <cmath>
#include <vector>

namespace aether::world {
namespace {

[[nodiscard]] Result<void>
validateNodeList(std::span<const std::size_t> nodes, std::size_t nodeCount,
                 const char* label) {
    for (const std::size_t node : nodes) {
        if (node >= nodeCount)
            return fail(ErrorCode::invalidArgument,
                        std::string(label) + " contains an out-of-range node");
    }
    return {};
}

void sortUnique(std::vector<std::size_t>& values) {
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
}

} // namespace

Result<RevisionGraph>
RevisionGraph::build(std::size_t nodeCount,
                     std::span<const RevisionDependency> dependencies) {
    if (nodeCount == 0)
        return fail(ErrorCode::invalidArgument,
                    "Revision graph requires at least one node");

    RevisionGraph graph;
    graph.nodeCount_ = nodeCount;
    graph.dependencies_.assign(dependencies.begin(), dependencies.end());
    graph.predecessors_.resize(nodeCount);
    graph.failClosedSuccessors_.resize(nodeCount);

    for (const RevisionDependency& dependency : graph.dependencies_) {
        if (dependency.source >= nodeCount || dependency.target >= nodeCount) {
            return fail(ErrorCode::invalidArgument,
                        "Revision dependency endpoint is out of range");
        }

        switch (dependency.dependencyClass) {
        case RevisionDependencyClass::hard:
            if (dependency.gain.has_value()) {
                return fail(ErrorCode::invalidArgument,
                            "HARD revision dependency must not carry an approximate gain");
            }
            break;
        case RevisionDependencyClass::analytic:
            if (!dependency.gain.has_value() ||
                !std::isfinite(*dependency.gain) || *dependency.gain < 0.0) {
                return fail(ErrorCode::invalidArgument,
                            "ANALYTIC revision dependency requires a finite non-negative gain");
            }
            if (dependency.boundId.empty()) {
                return fail(ErrorCode::invalidArgument,
                            "ANALYTIC revision dependency requires bound provenance");
            }
            break;
        case RevisionDependencyClass::empirical:
            if (dependency.gain.has_value() &&
                (!std::isfinite(*dependency.gain) || *dependency.gain < 0.0)) {
                return fail(ErrorCode::invalidArgument,
                            "EMPIRICAL revision estimate must be finite and non-negative");
            }
            break;
        }

        graph.predecessors_[dependency.target].push_back(dependency.source);
        if (dependency.dependencyClass == RevisionDependencyClass::hard ||
            dependency.dependencyClass == RevisionDependencyClass::empirical) {
            graph.failClosedSuccessors_[dependency.source].push_back(
                dependency.target);
        }
    }

    for (auto& values : graph.predecessors_)
        sortUnique(values);
    for (auto& values : graph.failClosedSuccessors_)
        sortUnique(values);

    return graph;
}

Result<std::vector<std::size_t>>
RevisionGraph::hardForwardClosure(std::span<const std::size_t> sources) const {
    if (auto valid = validateNodeList(sources, nodeCount_, "Revision source");
        !valid) {
        return std::unexpected(valid.error());
    }

    std::vector<bool> included(nodeCount_, false);
    std::vector<std::size_t> stack;
    stack.reserve(sources.size());

    for (const std::size_t source : sources) {
        if (!included[source]) {
            included[source] = true;
            stack.push_back(source);
        }
    }

    while (!stack.empty()) {
        const std::size_t node = stack.back();
        stack.pop_back();
        for (const std::size_t successor : failClosedSuccessors_[node]) {
            if (!included[successor]) {
                included[successor] = true;
                stack.push_back(successor);
            }
        }
    }

    std::vector<std::size_t> closure;
    for (std::size_t node = 0; node < nodeCount_; ++node)
        if (included[node])
            closure.push_back(node);
    return closure;
}

Result<std::vector<std::size_t>>
RevisionGraph::activePredecessorClosure(
    std::span<const std::size_t> seed,
    std::span<const double> trueChangeBounds) const {
    if (auto valid = validateNodeList(seed, nodeCount_, "Repair cone seed");
        !valid) {
        return std::unexpected(valid.error());
    }
    if (trueChangeBounds.size() != nodeCount_) {
        return fail(ErrorCode::invalidArgument,
                    "Revision true-change bound count does not match graph node count");
    }
    for (const double bound : trueChangeBounds) {
        if (!std::isfinite(bound) || bound < 0.0) {
            return fail(ErrorCode::invalidArgument,
                        "Revision true-change bounds must be finite and non-negative");
        }
    }

    std::vector<bool> included(nodeCount_, false);
    std::vector<std::size_t> stack;
    stack.reserve(seed.size());

    for (const std::size_t node : seed) {
        if (!included[node]) {
            included[node] = true;
            stack.push_back(node);
        }
    }

    while (!stack.empty()) {
        const std::size_t node = stack.back();
        stack.pop_back();
        for (const std::size_t predecessor : predecessors_[node]) {
            if (trueChangeBounds[predecessor] <= 0.0 || included[predecessor])
                continue;
            included[predecessor] = true;
            stack.push_back(predecessor);
        }
    }

    std::vector<std::size_t> closure;
    for (std::size_t node = 0; node < nodeCount_; ++node)
        if (included[node])
            closure.push_back(node);
    return closure;
}

Result<bool>
RevisionGraph::isActivePredecessorConsistent(
    std::span<const std::size_t> cone,
    std::span<const double> trueChangeBounds) const {
    auto closure = activePredecessorClosure(cone, trueChangeBounds);
    if (!closure)
        return std::unexpected(closure.error());

    std::vector<std::size_t> normalized(cone.begin(), cone.end());
    sortUnique(normalized);
    return normalized == *closure;
}

} // namespace aether::world
