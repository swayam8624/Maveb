#pragma once

#include <aether/core/Error.hpp>

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace aether::world {

enum class RevisionDependencyClass : std::uint8_t {
    hard = 0,
    analytic,
    empirical,
};

struct RevisionDependency final {
    std::size_t source{};
    std::size_t target{};
    RevisionDependencyClass dependencyClass{RevisionDependencyClass::hard};
    std::optional<double> gain;
    std::string boundId;
};

/// Sparse typed dependency graph for CBRC execution.
///
/// Two closures are intentionally separate:
///
/// 1. hardForwardClosure(): physical change propagates forward through HARD and
///    EMPIRICAL edges, because empirical-only dependencies do not have a safe
///    approximation bound.
/// 2. activePredecessorClosure(): a candidate repair cone is closed backward
///    over *all* dependency classes, but only when the predecessor's true-change
///    upper bound is non-zero. Unchanged predecessors remain valid without repair.
class RevisionGraph final {
  public:
    [[nodiscard]] static Result<RevisionGraph>
    build(std::size_t nodeCount, std::span<const RevisionDependency> dependencies);

    [[nodiscard]] std::size_t nodeCount() const noexcept { return nodeCount_; }
    [[nodiscard]] std::span<const RevisionDependency> dependencies() const noexcept {
        return dependencies_;
    }

    [[nodiscard]] Result<std::vector<std::size_t>>
    hardForwardClosure(std::span<const std::size_t> sources) const;

    [[nodiscard]] Result<std::vector<std::size_t>>
    activePredecessorClosure(std::span<const std::size_t> seed,
                             std::span<const double> trueChangeBounds) const;

    [[nodiscard]] Result<bool>
    isActivePredecessorConsistent(std::span<const std::size_t> cone,
                                  std::span<const double> trueChangeBounds) const;

  private:
    std::size_t nodeCount_{};
    std::vector<RevisionDependency> dependencies_;
    std::vector<std::vector<std::size_t>> predecessors_;
    std::vector<std::vector<std::size_t>> failClosedSuccessors_;
};

} // namespace aether::world
