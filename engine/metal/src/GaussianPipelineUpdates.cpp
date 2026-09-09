#include <aether/metal/GaussianPipeline.hpp>

#include <algorithm>
#include <cmath>
#include <vector>

namespace aether::metal {

Result<void>
GaussianPipeline::validateTranslation(std::span<const std::uint32_t> gaussianIndices,
                                      simd_float3 translationDelta) const {
    if (!gaussians_ || gaussianCount_ == 0)
        return fail(ErrorCode::notFound, "Gaussian translation requires a loaded GPU scene");
    if (!std::isfinite(translationDelta.x) || !std::isfinite(translationDelta.y) ||
        !std::isfinite(translationDelta.z)) {
        return fail(ErrorCode::invalidArgument, "Gaussian GPU translation delta must be finite");
    }
    if (gaussianIndices.empty())
        return {};

    std::vector<std::uint32_t> sorted(gaussianIndices.begin(), gaussianIndices.end());
    std::sort(sorted.begin(), sorted.end());
    if (std::adjacent_find(sorted.begin(), sorted.end()) != sorted.end()) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian GPU translation indices must be unique");
    }
    if (sorted.back() >= gaussianCount_)
        return fail(ErrorCode::invalidArgument, "Gaussian GPU translation index is out of range");

    const auto* primitives = static_cast<const AetherGaussianGpu*>(gaussians_->contents());
    if (!primitives)
        return fail(ErrorCode::metal, "Gaussian shared GPU buffer is not CPU-addressable");

    for (const std::uint32_t index : sorted) {
        const simd_float4 current = primitives[index].positionOpacity;
        if (!std::isfinite(current.x + translationDelta.x) ||
            !std::isfinite(current.y + translationDelta.y) ||
            !std::isfinite(current.z + translationDelta.z)) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian GPU translation would produce a non-finite position");
        }
    }
    return {};
}

Result<void> GaussianPipeline::translate(std::span<const std::uint32_t> gaussianIndices,
                                         simd_float3 translationDelta) {
    if (auto validation = validateTranslation(gaussianIndices, translationDelta); !validation)
        return std::unexpected(validation.error());
    if (gaussianIndices.empty())
        return {};

    std::vector<std::uint32_t> sorted(gaussianIndices.begin(), gaussianIndices.end());
    std::sort(sorted.begin(), sorted.end());
    auto* primitives = static_cast<AetherGaussianGpu*>(gaussians_->contents());
    for (const std::uint32_t index : sorted) {
        primitives[index].positionOpacity.x += translationDelta.x;
        primitives[index].positionOpacity.y += translationDelta.y;
        primitives[index].positionOpacity.z += translationDelta.z;
    }
    return {};
}

} // namespace aether::metal
