#include <aether/scene/TemporalRevisionCertificate.hpp>

#include <algorithm>
#include <cmath>

namespace aether::scene {
namespace {

[[nodiscard]] bool validBound(double value) noexcept {
    return std::isfinite(value) && value >= 0.0;
}

} // namespace

Result<TemporalRevisionCertificate>
certifyTemporalRevision(double currentErrorBound, double historyErrorBound,
                        double currentNeighborhoodExtremaErrorBound, double historyWeight,
                        bool validationDecisionStable) {
    if (!validBound(currentErrorBound) || !validBound(historyErrorBound) ||
        !validBound(currentNeighborhoodExtremaErrorBound))
        return fail(ErrorCode::invalidArgument,
                    "Temporal revision certificate error bounds must be finite and non-negative");
    if (!std::isfinite(historyWeight) || historyWeight < 0.0 || historyWeight > 1.0)
        return fail(ErrorCode::invalidArgument,
                    "Temporal revision certificate history weight must lie in [0,1]");

    if (!validationDecisionStable) {
        return TemporalRevisionCertificate{
            .requiresHardInvalidation = true,
            .retainedHistoryInputBound = 0.0,
            .resolvedOutputBound = currentErrorBound,
        };
    }

    const double retainedHistoryBound =
        std::max(historyErrorBound, currentNeighborhoodExtremaErrorBound);
    const double outputBound =
        (1.0 - historyWeight) * currentErrorBound + historyWeight * retainedHistoryBound;
    if (!std::isfinite(outputBound))
        return fail(ErrorCode::resourceExhausted, "Temporal revision certificate bound overflow");

    return TemporalRevisionCertificate{
        .requiresHardInvalidation = false,
        .retainedHistoryInputBound = retainedHistoryBound,
        .resolvedOutputBound = outputBound,
    };
}

Result<double> temporalHistoryDecayBound(double initialHistoryErrorBound, double historyWeight,
                                         unsigned frames) {
    if (!validBound(initialHistoryErrorBound))
        return fail(ErrorCode::invalidArgument,
                    "Temporal history decay initial bound must be finite and non-negative");
    if (!std::isfinite(historyWeight) || historyWeight < 0.0 || historyWeight > 1.0)
        return fail(ErrorCode::invalidArgument, "Temporal history decay weight must lie in [0,1]");

    const double result =
        initialHistoryErrorBound * std::pow(historyWeight, static_cast<double>(frames));
    if (!std::isfinite(result))
        return fail(ErrorCode::resourceExhausted, "Temporal history decay bound overflow");
    return result;
}

} // namespace aether::scene
