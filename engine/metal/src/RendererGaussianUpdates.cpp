#include <aether/metal/Renderer.hpp>

#include <cmath>

namespace aether::metal {

Result<void>
Renderer::validateGaussianTranslation(std::span<const std::uint32_t> gaussianIndices,
                                      simd_float3 translationDelta) const {
    if (!gaussianPipeline_)
        return fail(ErrorCode::notFound, "Gaussian translation requires an active captured scene");
    return gaussianPipeline_->validateTranslation(gaussianIndices, translationDelta);
}

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

    // Local edits mutate canonical CPU state and append a publication journal entry only.
    // Each recycled frame slot receives its stale record ranges immediately before that slot is
    // encoded, so no edit waits for or mutates an in-flight GPU source buffer.
    auto translated = gaussianPipeline_->translate(gaussianIndices, translationDelta);
    if (!translated)
        return std::unexpected(translated.error());

    lastGaussianEditPublicationStatistics_ = {
        .sourceBuffer = gaussianPipeline_->publicationStatistics(),
        .frameSlotsQuiesced = 0,
        .globalTemporalHistoryInvalidated = true,
    };

    // Reprojection after an authored spatial edit must not blend against history generated from
    // the pre-edit geometry. This global invalidation is intentionally preserved as the correctness
    // baseline; the temporal-locality research branch must beat it without introducing ghosting.
    temporalHistoryValid_ = false;
    return {};
}

} // namespace aether::metal
