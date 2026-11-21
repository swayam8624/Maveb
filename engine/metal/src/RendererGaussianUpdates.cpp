// LEARNING MAP — GPU-facing Gaussian edit publication. This Renderer method
// delegates to GaussianPipeline for validation and mutation, then tracks
// temporal invalidation so a new frame does not reuse stale history.
// It does not itself certify that a local revision meets an output tolerance.
// See READING_ORDER.md for the planner -> renderer -> oracle boundary.

#include <aether/metal/Renderer.hpp>

#include <cmath>

namespace aether::metal {

Result<void> Renderer::validateGaussianTranslation(std::span<const std::uint32_t> gaussianIndices,
                                                   simd_float3 translationDelta) const {
    if (!gaussianPipeline_)
        return fail(ErrorCode::notFound, "Gaussian translation requires an active captured scene");
    return gaussianPipeline_->validateTranslation(gaussianIndices, translationDelta);
}

// Called only after the app or revision system has chosen an edit. The
// Gaussian pipeline owns GPU buffers; the renderer propagates invalidation
// so downstream temporal rendering cannot silently reuse stale results.
Result<void> Renderer::translateGaussians(std::span<const std::uint32_t> gaussianIndices,
                                          simd_float3 translationDelta) {
    if (!gaussianPipeline_)
        return fail(ErrorCode::notFound, "Gaussian translation requires an active captured scene");
    if (!std::isfinite(translationDelta.x) || !std::isfinite(translationDelta.y) ||
        !std::isfinite(translationDelta.z)) {
        return fail(ErrorCode::invalidArgument,
                    "Renderer Gaussian translation delta must be finite");
    }
    if (gaussianIndices.empty())
        return {};

    auto editBounds = gaussianPipeline_->translationBounds(gaussianIndices, translationDelta);
    if (!editBounds)
        return std::unexpected(editBounds.error());

    // The edit mutates canonical CPU state and journals changed IDs only. No submitted frame-slot
    // source buffer is touched here; stale records are copied when each slot is recycled.
    auto translated = gaussianPipeline_->translate(gaussianIndices, translationDelta);
    if (!translated)
        return std::unexpected(translated.error());

    lastGaussianEditPublicationStatistics_ = {
        .sourceBuffer = gaussianPipeline_->publicationStatistics(),
        .frameSlotsQuiesced = 0,
        .globalTemporalHistoryInvalidated = false,
    };

    const scene::TemporalWorldBounds currentBounds{
        .minimum = editBounds->minimum,
        .maximum = editBounds->maximum,
    };
    if (pendingTemporalInvalidationBounds_) {
        *pendingTemporalInvalidationBounds_ =
            scene::mergeTemporalWorldBounds(*pendingTemporalInvalidationBounds_, currentBounds);
    } else {
        pendingTemporalInvalidationBounds_ = currentBounds;
    }
    lastTemporalInvalidationPlan_ = {};
    return {};
}

} // namespace aether::metal
