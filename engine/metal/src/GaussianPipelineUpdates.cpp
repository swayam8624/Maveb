#include <aether/metal/GaussianPipeline.hpp>

#include <aether/gaussian/GaussianUpdatePlan.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <vector>

namespace aether::metal {
namespace {

[[nodiscard]] Result<gaussian::Gaussian> decodeCanonicalGaussian(const AetherGaussianGpu& source) {
    gaussian::Gaussian result;
    result.position = {
        source.positionOpacity.x,
        source.positionOpacity.y,
        source.positionOpacity.z,
    };
    result.opacityLogit = source.positionOpacity.w;
    result.logScale = {
        source.logScaleRestCount.x,
        source.logScaleRestCount.y,
        source.logScaleRestCount.z,
    };
    result.rotation = {
        source.rotation.x,
        source.rotation.y,
        source.rotation.z,
        source.rotation.w,
    };
    result.dc = {source.dc.x, source.dc.y, source.dc.z};

    const double restCountValue = static_cast<double>(source.logScaleRestCount.w);
    if (!std::isfinite(restCountValue))
        return fail(ErrorCode::corruptData, "Canonical Gaussian rest count is non-finite");
    const auto rounded = static_cast<std::size_t>(std::llround(restCountValue));
    if (std::abs(restCountValue - static_cast<double>(rounded)) > 1.0e-4 ||
        (rounded != 0 && rounded != 9 && rounded != 24 && rounded != 45)) {
        return fail(ErrorCode::corruptData, "Canonical Gaussian rest count is invalid");
    }
    result.restCount = rounded;
    for (std::size_t coefficient = 0; coefficient < result.rest.size(); ++coefficient) {
        result.rest[coefficient] = source.shRest[coefficient / 4][coefficient % 4];
    }
    return result;
}

[[nodiscard]] std::size_t shDegree(std::size_t restCount) noexcept {
    return restCount >= 45 ? 3 : restCount >= 24 ? 2 : restCount >= 9 ? 1 : 0;
}

} // namespace

Result<void>
GaussianPipeline::validateTranslationLocked(std::span<const std::uint32_t> gaussianIndices,
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
        return fail(ErrorCode::invalidArgument, "Gaussian GPU translation indices must be unique");
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

Result<void> GaussianPipeline::validateTranslation(std::span<const std::uint32_t> gaussianIndices,
                                                   simd_float3 translationDelta) const {
    std::scoped_lock lock(publicationMutex_);
    return validateTranslationLocked(gaussianIndices, translationDelta);
}

Result<GaussianEditBounds>
GaussianPipeline::translationBounds(std::span<const std::uint32_t> gaussianIndices,
                                    simd_float3 translationDelta) const {
    std::scoped_lock lock(publicationMutex_);
    if (auto validation = validateTranslationLocked(gaussianIndices, translationDelta); !validation)
        return std::unexpected(validation.error());
    if (gaussianIndices.empty())
        return fail(ErrorCode::invalidArgument, "Gaussian edit bounds require at least one ID");

    const float infinity = std::numeric_limits<float>::infinity();
    GaussianEditBounds result{
        .minimum = {infinity, infinity, infinity},
        .maximum = {-infinity, -infinity, -infinity},
    };

    for (const std::uint32_t index : gaussianIndices) {
        const auto& primitive = canonicalGaussians_[index];
        const float maximumLogScale =
            std::max({primitive.logScaleRestCount.x, primitive.logScaleRestCount.y,
                      primitive.logScaleRestCount.z});
        const float radius = 3.0F * std::exp(maximumLogScale);
        if (!std::isfinite(radius))
            return fail(ErrorCode::resourceExhausted, "Gaussian edit bound radius is non-finite");

        const simd_float3 oldCenter{
            primitive.positionOpacity.x,
            primitive.positionOpacity.y,
            primitive.positionOpacity.z,
        };
        const simd_float3 newCenter = oldCenter + translationDelta;
        const simd_float3 extent{radius, radius, radius};

        result.minimum = simd_min(result.minimum, oldCenter - extent);
        result.minimum = simd_min(result.minimum, newCenter - extent);
        result.maximum = simd_max(result.maximum, oldCenter + extent);
        result.maximum = simd_max(result.maximum, newCenter + extent);
    }
    return result;
}

Result<void> GaussianPipeline::translate(std::span<const std::uint32_t> gaussianIndices,
                                         simd_float3 translationDelta) {
    std::scoped_lock lock(publicationMutex_);
    if (auto validation = validateTranslationLocked(gaussianIndices, translationDelta); !validation)
        return std::unexpected(validation.error());

    auto publication = gaussian::planGaussianPublication(gaussianIndices, gaussianCount_,
                                                         sizeof(AetherGaussianGpu));
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
        return fail(ErrorCode::resourceExhausted, "Gaussian publication version counter exhausted");

    std::vector<std::uint32_t> sorted(gaussianIndices.begin(), gaussianIndices.end());
    std::sort(sorted.begin(), sorted.end());
    for (const std::uint32_t index : sorted) {
        pendingRevisionBefore_.try_emplace(index, canonicalGaussians_[index]);
        canonicalGaussians_[index].positionOpacity.x += translationDelta.x;
        canonicalGaussians_[index].positionOpacity.y += translationDelta.y;
        canonicalGaussians_[index].positionOpacity.z += translationDelta.z;
    }

    ++currentVersion_;
    publicationJournal_.push_back(
        PublicationPatch{.version = currentVersion_, .indices = std::move(sorted)});
    return {};
}

Result<GaussianRevisionSnapshot> GaussianPipeline::pendingRevisionSnapshot() const {
    std::scoped_lock lock(publicationMutex_);
    if (pendingRevisionBefore_.empty())
        return fail(ErrorCode::notFound, "Gaussian revision snapshot has no pending edits");

    std::vector<std::uint32_t> indices;
    indices.reserve(pendingRevisionBefore_.size());
    for (const auto& entry : pendingRevisionBefore_)
        indices.push_back(entry.first);
    std::sort(indices.begin(), indices.end());

    GaussianRevisionSnapshot snapshot;
    snapshot.version = currentVersion_;
    snapshot.sourceIndices = indices;
    snapshot.sceneColorUpperBound = sceneColorUpperBound_;
    snapshot.beforeChanged.name = "pending-revision-before";
    snapshot.afterChanged.name = "pending-revision-after";
    snapshot.beforeChanged.gaussians.reserve(indices.size());
    snapshot.afterChanged.gaussians.reserve(indices.size());

    std::size_t degree{};
    for (const std::uint32_t index : indices) {
        const auto beforeIt = pendingRevisionBefore_.find(index);
        if (beforeIt == pendingRevisionBefore_.end() || index >= canonicalGaussians_.size()) {
            return fail(ErrorCode::corruptData,
                        "Gaussian revision journal contains an invalid source index");
        }

        auto before = decodeCanonicalGaussian(beforeIt->second);
        if (!before)
            return std::unexpected(before.error());
        auto after = decodeCanonicalGaussian(canonicalGaussians_[index]);
        if (!after)
            return std::unexpected(after.error());

        degree =
            std::max(degree, std::max(shDegree(before->restCount), shDegree(after->restCount)));
        snapshot.beforeChanged.gaussians.push_back(*before);
        snapshot.afterChanged.gaussians.push_back(*after);
    }
    snapshot.beforeChanged.sphericalHarmonicDegree = degree;
    snapshot.afterChanged.sphericalHarmonicDegree = degree;
    return snapshot;
}

void GaussianPipeline::clearPendingRevisionSnapshot() noexcept {
    std::scoped_lock lock(publicationMutex_);
    pendingRevisionBefore_.clear();
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

    const std::size_t fullBytes = canonicalGaussians_.size() * sizeof(AetherGaussianGpu);
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

    auto plan =
        gaussian::planGaussianPublication(changed, gaussianCount_, sizeof(AetherGaussianGpu));
    if (!plan)
        return std::unexpected(plan.error());
    if (changed.empty()) {
        return fail(ErrorCode::corruptData,
                    "Gaussian publication journal lost a required frame-slot update");
    }

    auto* destination = static_cast<std::byte*>(gaussianSources_[frameSlot]->contents());
    if (!destination)
        return fail(ErrorCode::metal, "Gaussian frame source buffer is not CPU-addressable");

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
