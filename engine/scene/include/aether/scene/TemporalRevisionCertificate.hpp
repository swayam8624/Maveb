#pragma once

#include <aether/core/Error.hpp>

namespace aether::scene {

struct TemporalRevisionCertificate final {
    bool requiresHardInvalidation{};
    double retainedHistoryInputBound{};
    double resolvedOutputBound{};
};

/// Conservative one-frame bound for the production temporal resolve.
///
/// The retained history sample is clamped to the current neighborhood before
/// blending. Componentwise clamp/projection is non-expansive in the history
/// sample; if the clamp interval itself changes, its endpoint motion is bounded
/// by currentNeighborhoodExtremaErrorBound. Therefore the clamped-history
/// difference is bounded by:
///
///   max(historyErrorBound, currentNeighborhoodExtremaErrorBound).
///
/// With history weight w, the resolved output obeys:
///
///   e_out <= (1-w) e_current
///            + w max(e_history, e_neighborhood).
///
/// The formula is only a soft certificate when the history validation decision
/// (reprojection, depth/disocclusion, bounds validity) is guaranteed stable
/// across the revision. If not, this function requires HARD invalidation and
/// reports the post-invalidation bound as currentErrorBound.
[[nodiscard]] Result<TemporalRevisionCertificate>
certifyTemporalRevision(double currentErrorBound,
                        double historyErrorBound,
                        double currentNeighborhoodExtremaErrorBound,
                        double historyWeight,
                        bool validationDecisionStable);

/// Repeated stable-history propagation with no further current-frame
/// disturbance. After frames steps, an initial history error e0 is bounded by
/// w^frames e0.
[[nodiscard]] Result<double>
temporalHistoryDecayBound(double initialHistoryErrorBound,
                          double historyWeight,
                          unsigned frames);

} // namespace aether::scene
