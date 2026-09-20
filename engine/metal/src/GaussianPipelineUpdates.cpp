#include <aether/metal/GaussianPipeline.hpp>

#include <aether/gaussian/GaussianUpdatePlan.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <vector>

namespace aether::metal {

Result<void>
GaussianPipeline::validateTranslationLocked(
    std::span<const std::uint32_t> gaussianIndices,
    simd_float3 translationDelta) const {
    if (canonicalGaussians_.empty() || gaussianCount_ == 0)
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

    for (const std::uint32_t index : sorted) {
        const simd_float4 current = canonicalGaussians_[index].positionOpacity;
        if (!std::isfinite(current.x + translationDelta.x) ||
            !std::isfinite(current.y + translationDelta.y) ||
            !std::isfinite(current.z + translationDelta.z)) {
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian GPU translation would produce a non-finite position");
        }
    }
    return {};
}

Result<void>
GaussianPipeline::validateTranslation(
    std::span<const std::uint32_t> gaussianIndices,
    simd_float3 translationDelta) const {
    std::scoped_lock lock(publicationMutex_);
    return validateTranslationLocked(gaussianIndices, translationDelta);
}

Result<void>
GaussianPipeline::translate(std::span<const std::uint32_t> gaussianIndices,
                            simd_float3 translationDelta) {
    std::scoped_lock lock(publicationMutex_);
    if (auto validation = validateTranslationLocked(gaussianIndices, translationDelta); !validation)
        return std::unexpected(validation.error());

    auto publication = gaussian::planGaussianPublication(
        gaussianIndices, gaussianCount_, sizeof(AetherGaussianGpu));
    if (!publication)
        return std::unexpected(publication.error());

    lastPublicationStatistics_ = {
        .touchedRecords = publication->touchedRecords,
        .contiguousRanges = publication->ranges.size(),
        .touchedBytes = publication->touchedBytes,
        .fullBufferBytes = publication->fullBufferBytes,
    };
    if (gaussianIndices.empty())
        return {};

    if (currentVersion_ == std::numeric_limits<std::uint64_t>::max())
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian publication version counter exhausted");

    std::vector<std::uint32_t> sorted(gaussianIndices.begin(), gaussianIndices.end());
    std::sort(sorted.begin(), sorted.end());
    for (const std::uint32_t index : sorted) {
        canonicalGaussians_[index].positionOpacity.x += translationDelta.x;
        canonicalGaussians_[index].positionOpacity.y += translationDelta.y;
        canonicalGaussians_[index].positionOpacity.z += translationDelta.z;
    }

    ++currentVersion_;
    publicationJournal_.push_back(
        PublicationPatch{.version = currentVersion_, .indices = std::move(sorted)});
    return {};
}

void GaussianPipeline::collectPublishedJournalLocked() noexcept {
    const std::uint64_t minimumVersion =
        *std::min_element(sourceVersions_.begin(), sourceVersions_.end());
    std::erase_if(publicationJournal_, [minimumVersion](const PublicationPatch& patch) {
        return patch.version <= minimumVersion;
    });
}

Result<void> GaussianPipeline::publishFrameSlot(std::size_t frameSlot) {
    std::scoped_lock lock(publicationMutex_);
    if (frameSlot >= gaussianSources_.size())
        return fail(ErrorCode::invalidArgument, "Gaussian frame publication slot is out of range");
    if (!gaussianSources_[frameSlot] || canonicalGaussians_.empty() || gaussianCount_ == 0)
        return fail(ErrorCode::notFound, "Gaussian frame publication requires a loaded scene");

    const std::size_t fullBytes =
        canonicalGaussians_.size() * sizeof(AetherGaussianGpu);
    if (sourceVersions_[frameSlot] == currentVersion_) {
        lastFramePublicationStatistics_ = {
            .touchedRecords = 0,
            .contiguousRanges = 0,
            .touchedBytes = 0,
            .fullBufferBytes = fullBytes,
        };
        return {};
    }

    std::vector<std::uint32_t> changed;
    for (const PublicationPatch& patch : publicationJournal_) {
        if (patch.version <= sourceVersions_[frameSlot])
            continue;
        changed.insert(changed.end(), patch.indices.begin(), patch.indices.end());
    }
    std::sort(changed.begin(), changed.end());
    changed.erase(std::unique(changed.begin(), changed.end()), changed.end());

    auto plan = gaussian::planGaussianPublication(
        changed, gaussianCount_, sizeof(AetherGaussianGpu));
    if (!plan)
        return std::unexpected(plan.error());
    if (changed.empty()) {
        return fail(ErrorCode::corruptData,
                    "Gaussian publication journal lost a required frame-slot update");
    }

    auto* destination =
        static_cast<std::byte*>(gaussianSources_[frameSlot]->contents());
    if (!destination)
        return fail(ErrorCode::metal,
                    "Gaussian frame source buffer is not CPU-addressable");

    for (const gaussian::GaussianPublicationRange& range : plan->ranges) {
        const std::size_t first = static_cast<std::size_t>(range.firstIndex);
        const std::size_t count = static_cast<std::size_t>(range.count);
        const std::size_t offset = first * sizeof(AetherGaussianGpu);
        const std::size_t bytes = count * sizeof(AetherGaussianGpu);
        std::memcpy(destination + offset, canonicalGaussians_.data() + first, bytes);
    }

    sourceVersions_[frameSlot] = currentVersion_;
    lastFramePublicationStatistics_ = {
        .touchedRecords = plan->touchedRecords,
        .contiguousRanges = plan->ranges.size(),
        .touchedBytes = plan->touchedBytes,
        .fullBufferBytes = plan->fullBufferBytes,
    };
    collectPublishedJournalLocked();
    return {};
}

} // namespace aether::metal
