#pragma once

#include <aether/core/Error.hpp>

#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace aether::revision {

using RevisionNodeId = std::uint32_t;

enum class RevisionEdgeClass : std::uint8_t {
    hard,
    analytic,
    empirical,
};

struct RevisionNode final {
    std::string name;
    /// Frozen scalar planner cost in one common calibrated unit (for example ms).
    double workCost{};
    /// Conservative normalized finite-change magnitude used when this repaired
    /// node drives an analytic edge across the cone frontier.
    double changeBound{};
};

struct RevisionEdge final {
    RevisionNodeId source{};
    RevisionNodeId target{};
    RevisionEdgeClass edgeClass{RevisionEdgeClass::hard};
    /// ANALYTIC: conservative non-negative finite-change gain.
    /// EMPIRICAL: optional non-negative scheduling estimate; never certifies.
    /// HARD: must be zero.
    double gain{};
    /// Required for ANALYTIC edges to retain proof/bound provenance.
    std::string boundId;
};

struct RevisionQoITerm final {
    RevisionNodeId node{};
    double weight{};
};

struct RevisionQoI final {
    std::string name;
    std::vector<RevisionQoITerm> terms;
    double epsilon{};
};

struct RevisionQoIResult final {
    std::string name;
    double bound{};
    double epsilon{};
};

struct RevisionConeCertificate final {
    std::vector<RevisionNodeId> cone;
    std::vector<RevisionNodeId> exterior;
    std::vector<RevisionQoIResult> qois;
    bool stable{};
    bool passes{};
    bool fullRebuild{};
    std::string reason;
    double work{};
    double fullWork{};
};

class RevisionGraph final {
  public:
    [[nodiscard]] static Result<RevisionGraph>
    build(std::vector<RevisionNode> nodes, std::vector<RevisionEdge> edges,
          std::optional<double> fullWorkBaseline = std::nullopt);

    [[nodiscard]] std::size_t nodeCount() const noexcept {
        return nodes_.size();
    }
    [[nodiscard]] const RevisionNode& node(RevisionNodeId id) const noexcept {
        return nodes_[id];
    }
    [[nodiscard]] const std::vector<RevisionEdge>& edges() const noexcept {
        return edges_;
    }
    [[nodiscard]] double fullWorkBaseline() const noexcept {
        return fullWorkBaseline_;
    }

    /// HARD and EMPIRICAL edges are exact for certification. This closure only
    /// enforces predecessor consistency. Domain-specific forward hard
    /// invalidation must already be included in the caller-supplied hard seed.
    [[nodiscard]] Result<std::vector<RevisionNodeId>>
    closeExactPredecessors(std::span<const RevisionNodeId> seed) const;

  private:
    std::vector<RevisionNode> nodes_;
    std::vector<RevisionEdge> edges_;
    std::vector<std::vector<RevisionNodeId>> exactPredecessors_;
    std::vector<std::vector<std::size_t>> analyticOutgoing_;
    double fullWorkBaseline_{};
};

/// sourceBounds[node] is a conservative direct disturbance remaining at the
/// node if it lies outside the repaired cone. The caller normally sets direct
/// changed HARD nodes in the hard closure so their exterior source is absent.
[[nodiscard]] Result<RevisionConeCertificate>
certifyRevisionCone(const RevisionGraph& graph, std::span<const double> sourceBounds,
                    std::span<const RevisionNodeId> cone, std::span<const RevisionQoI> qois);

/// Greedy certified feasible-cone search. This is not a proof of combinatorial
/// global optimality. It expands the exact-predecessor-consistent hard seed
/// until every QoI passes, or returns the principled full-rebuild fallback.
///
/// Cyclic ANALYTIC exterior response is deliberately unsupported in v1; such a
/// candidate is unstable and the search must expand/break the cycle or rebuild.
[[nodiscard]] Result<RevisionConeCertificate>
greedyCertifiedRevisionCone(const RevisionGraph& graph, std::span<const double> sourceBounds,
                            std::span<const RevisionNodeId> hardClosure,
                            std::span<const RevisionQoI> qois);

} // namespace aether::revision
