#pragma once

#include <aether/core/Error.hpp>
#include <aether/world/RevisionGraph.hpp>

#include <cstddef>
#include <span>
#include <string>
#include <vector>

namespace aether::world {

struct RevisionQoIContract final {
    std::string name;
    std::vector<double> nodeWeights;
    double epsilon{};
};

struct RevisionQoIBound final {
    std::string name;
    double epsilon{};
    double certifiedBound{};
};

struct RevisionConeCertificate final {
    bool stable{};
    bool passes{};
    bool usedFullRebuild{};
    std::string reason;
    std::vector<std::size_t> cone;
    std::vector<std::size_t> exterior;
    std::vector<double> exteriorResidualBounds;
    std::vector<RevisionQoIBound> qoiBounds;
    double work{};
    double fullWork{};
};

/// Certifies a candidate CBRC cone when the unrepaired ANALYTIC exterior is a DAG.
///
/// For the exterior O, this computes the exact finite non-negative path sum:
///
///   z_O <= b_O + K_OC z_C + K_OO z_O
///
/// by topological propagation instead of forming a dense resolvent. HARD and
/// EMPIRICAL dependencies must already be covered by requiredRepairClosure().
/// If the active exact closure is not contained, the cone is rejected. If the
/// exterior ANALYTIC subgraph contains a cycle, this routine fails closed and
/// asks the caller to use the general resolvent reference or full rebuild.
[[nodiscard]] Result<RevisionConeCertificate>
certifyRevisionConeDAG(const RevisionGraph& graph,
                       std::span<const std::size_t> physicalSources,
                       std::span<const double> sourceBounds,
                       std::span<const double> trueChangeBounds,
                       std::span<const std::size_t> cone,
                       std::span<const double> work,
                       std::span<const RevisionQoIContract> qois);

} // namespace aether::world
