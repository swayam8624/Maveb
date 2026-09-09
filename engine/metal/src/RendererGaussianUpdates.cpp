#include <aether/metal/Renderer.hpp>

#include <cmath>

namespace aether::metal {
namespace {

/// Holds every renderer frame slot so no submitted command buffer can still read the shared
/// Gaussian source buffer while a CPU-side local edit is published.
class FrameQuiescence final {
  public:
    FrameQuiescence(dispatch_semaphore_t semaphore, std::size_t slotCount) noexcept
        : semaphore_(semaphore) {
        for (; acquired_ < slotCount; ++acquired_)
            dispatch_semaphore_wait(semaphore_, DISPATCH_TIME_FOREVER);
    }

    ~FrameQuiescence() {
        for (std::size_t index = 0; index < acquired_; ++index)
            dispatch_semaphore_signal(semaphore_);
    }

    FrameQuiescence(const FrameQuiescence&) = delete;
    FrameQuiescence& operator=(const FrameQuiescence&) = delete;

  private:
    dispatch_semaphore_t semaphore_{};
    std::size_t acquired_{};
};

} // namespace

Result<void> Renderer::translateGaussians(std::span<const std::uint32_t> gaussianIndices,
                                          simd_float3 translationDelta) {
    if (!gaussianPipeline_)
        return fail(ErrorCode::notFound, "Gaussian translation requires an active captured scene");
    if (!std::isfinite(translationDelta.x) || !std::isfinite(translationDelta.y) ||
        !std::isfinite(translationDelta.z)) {
        return fail(ErrorCode::invalidArgument, "Renderer Gaussian translation delta must be finite");
    }
    if (gaussianIndices.empty())
        return {};

    // draw() owns one semaphore slot from immediately before frame resource reuse until the Metal
    // command buffer completion handler fires. Owning every slot therefore proves that no in-flight
    // GPU command can still read GaussianPipeline's shared source buffer. New draw calls block at
    // the same semaphore until this scope exits.
    FrameQuiescence quiescence(frameSemaphore_, frameContexts_.size());
    auto translated = gaussianPipeline_->translate(gaussianIndices, translationDelta);
    if (!translated)
        return std::unexpected(translated.error());

    // Reprojection after an authored spatial edit must not blend against history generated from
    // the pre-edit geometry.
    temporalHistoryValid_ = false;
    return {};
}

} // namespace aether::metal
