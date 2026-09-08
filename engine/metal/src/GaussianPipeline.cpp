#include <aether/metal/GaussianPipeline.hpp>

#include "GaussianSpatialOrder.hpp"

#include <Foundation/Foundation.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <limits>
#include <string>

namespace aether::metal {
namespace {

enum PipelineIndex : std::size_t {
    project = 0,
    scanBlocks = 1,
    scanBlockSums = 2,
    addBlockOffsets = 3,
    generateKeys = 4,
    radixHistogram = 5,
    radixOffsets = 6,
    radixScatter = 7,
    initializeRanges = 8,
    buildRanges = 9,
    composite = 10,
    serialScan = 11,
    serialRadix = 12,
};

Result<MetalPtr<MTL::Buffer>> makeBuffer(MTL::Device* device, std::size_t bytes,
                                         MTL::ResourceOptions options, const char* label) {
    if (bytes == 0)
        return fail(ErrorCode::invalidArgument, "Metal buffer size cannot be zero", label);
    auto buffer = adopt(device->newBuffer(bytes, options));
    if (!buffer)
        return fail(ErrorCode::resourceExhausted, "Metal buffer allocation failed", label);
    buffer->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    return buffer;
}

} // namespace

Result<std::unique_ptr<GaussianPipeline>>
GaussianPipeline::create(MTL::Device* device, MTL::Library* library,
                         std::uint32_t maximumTileEntries) {
    if (!device || !library || maximumTileEntries == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian pipeline creation arguments are invalid");
    auto pipeline =
        std::unique_ptr<GaussianPipeline>(new GaussianPipeline(device, maximumTileEntries));
    if (auto result = pipeline->buildPipelines(library); !result)
        return std::unexpected(result.error());

    auto keysA =
        makeBuffer(device, static_cast<std::size_t>(maximumTileEntries) * sizeof(simd_uint2),
                   MTL::ResourceStorageModePrivate, "Gaussian Keys A");
    auto keysB =
        makeBuffer(device, static_cast<std::size_t>(maximumTileEntries) * sizeof(simd_uint2),
                   MTL::ResourceStorageModePrivate, "Gaussian Keys B");
    auto valuesA =
        makeBuffer(device, static_cast<std::size_t>(maximumTileEntries) * sizeof(std::uint32_t),
                   MTL::ResourceStorageModePrivate, "Gaussian Values A");
    auto valuesB =
        makeBuffer(device, static_cast<std::size_t>(maximumTileEntries) * sizeof(std::uint32_t),
                   MTL::ResourceStorageModePrivate, "Gaussian Values B");
    auto counters = makeBuffer(device, sizeof(AetherGaussianCounters),
                               MTL::ResourceStorageModeShared, "Gaussian Counters");
    const std::size_t radixGroupCount =
        (static_cast<std::size_t>(maximumTileEntries) + 255U) / 256U;
    auto radixHistograms = makeBuffer(device, radixGroupCount * 16U * sizeof(std::uint32_t),
                                      MTL::ResourceStorageModePrivate, "Gaussian Radix Histograms");
    auto radixGroupOffsets =
        makeBuffer(device, radixGroupCount * 16U * sizeof(std::uint32_t),
                   MTL::ResourceStorageModePrivate, "Gaussian Radix Group Offsets");
    auto indirectDispatch =
        makeBuffer(device, 3U * sizeof(std::uint32_t), MTL::ResourceStorageModePrivate,
                   "Gaussian Radix Indirect Dispatch");
    if (!keysA)
        return std::unexpected(keysA.error());
    if (!keysB)
        return std::unexpected(keysB.error());
    if (!valuesA)
        return std::unexpected(valuesA.error());
    if (!valuesB)
        return std::unexpected(valuesB.error());
    if (!counters)
        return std::unexpected(counters.error());
    if (!radixHistograms)
        return std::unexpected(radixHistograms.error());
    if (!radixGroupOffsets)
        return std::unexpected(radixGroupOffsets.error());
    if (!indirectDispatch)
        return std::unexpected(indirectDispatch.error());
    pipeline->keysA_ = std::move(*keysA);
    pipeline->keysB_ = std::move(*keysB);
    pipeline->valuesA_ = std::move(*valuesA);
    pipeline->valuesB_ = std::move(*valuesB);
    pipeline->counters_ = std::move(*counters);
    pipeline->radixHistograms_ = std::move(*radixHistograms);
    pipeline->radixGroupOffsets_ = std::move(*radixGroupOffsets);
    pipeline->indirectDispatch_ = std::move(*indirectDispatch);
    return pipeline;
}

GaussianPipeline::GaussianPipeline(MTL::Device* device, std::uint32_t maximumTileEntries)
    : device_(retain(device)), maximumTileEntries_(maximumTileEntries) {}

Result<void> GaussianPipeline::buildPipelines(MTL::Library* library) {
    constexpr std::array names{"aetherGaussianProject",          "aetherGaussianScanBlocks",
                               "aetherGaussianScanBlockSums",    "aetherGaussianAddBlockOffsets",
                               "aetherGaussianGenerateKeys",     "aetherGaussianRadixHistogram",
                               "aetherGaussianRadixOffsets",     "aetherGaussianRadixScatter",
                               "aetherGaussianInitializeRanges", "aetherGaussianBuildRanges",
                               "aetherGaussianComposite",        "aetherGaussianExclusiveScan",
                               "aetherGaussianStableRadixPass"};
    for (std::size_t index = 0; index < names.size(); ++index) {
        auto function =
            adopt(library->newFunction(NS::String::string(names[index], NS::UTF8StringEncoding)));
        if (!function)
            return fail(ErrorCode::metal, "Offline library is missing a Gaussian kernel",
                        names[index]);
        NS::Error* error = nullptr;
        pipelines_[index] = adopt(device_->newComputePipelineState(function.get(), &error));
        if (!pipelines_[index]) {
            const std::string context =
                error ? error->localizedDescription()->utf8String() : names[index];
            return fail(ErrorCode::metal, "Unable to create Gaussian compute pipeline", context);
        }
    }
    return {};
}

Result<void> GaussianPipeline::load(const gaussian::GaussianAsset& asset) {
    if (asset.gaussians.empty() ||
        asset.gaussians.size() > std::numeric_limits<std::uint32_t>::max()) {
        return fail(ErrorCode::resourceExhausted, "Gaussian asset count is empty or exceeds Metal");
    }

    const std::vector<std::uint32_t> progressiveOrder =
        detail::buildProgressiveSpatialOrder(asset);
    std::vector<AetherGaussianGpu> converted(asset.gaussians.size());
    for (std::size_t logicalIndex = 0; logicalIndex < asset.gaussians.size(); ++logicalIndex) {
        const std::uint32_t sourceIndex = progressiveOrder[logicalIndex];
        const gaussian::Gaussian& source = asset.gaussians[sourceIndex];
        AetherGaussianGpu& destination = converted[logicalIndex];
        destination.positionOpacity = {source.position[0], source.position[1], source.position[2],
                                       source.opacityLogit};
        destination.logScaleRestCount = {source.logScale[0], source.logScale[1], source.logScale[2],
                                         static_cast<float>(source.restCount)};
        destination.rotation = {source.rotation[0], source.rotation[1], source.rotation[2],
                                source.rotation[3]};
        // dc.w is unused by SH evaluation. Store the canonical source ID bit-exactly so a
        // spatially reordered preview can still report stable picking/debug IDs.
        destination.dc = {source.dc[0], source.dc[1], source.dc[2],
                          std::bit_cast<float>(sourceIndex)};
        for (std::size_t coefficient = 0; coefficient < source.rest.size(); ++coefficient) {
            destination.shRest[coefficient / 4][coefficient % 4] = source.rest[coefficient];
        }
    }
    auto gaussians = makeBuffer(device_.get(), converted.size() * sizeof(AetherGaussianGpu),
                                MTL::ResourceStorageModeShared, "Canonical Gaussians");
    auto projectedBuffer =
        makeBuffer(device_.get(), converted.size() * sizeof(AetherProjectedGaussian),
                   MTL::ResourceStorageModePrivate, "Projected Gaussians");
    auto counts = makeBuffer(device_.get(), converted.size() * sizeof(std::uint32_t),
                             MTL::ResourceStorageModePrivate, "Gaussian Tile Counts");
    auto offsets = makeBuffer(device_.get(), converted.size() * sizeof(std::uint32_t),
                              MTL::ResourceStorageModePrivate, "Gaussian Tile Offsets");
    const std::size_t scanBlockCount = (converted.size() + 255U) / 256U;
    auto scanBlockSums = makeBuffer(device_.get(), scanBlockCount * sizeof(std::uint32_t),
                                    MTL::ResourceStorageModePrivate, "Gaussian Scan Block Sums");
    if (!gaussians)
        return std::unexpected(gaussians.error());
    if (!projectedBuffer)
        return std::unexpected(projectedBuffer.error());
    if (!counts)
        return std::unexpected(counts.error());
    if (!offsets)
        return std::unexpected(offsets.error());
    if (!scanBlockSums)
        return std::unexpected(scanBlockSums.error());
    std::memcpy((*gaussians)->contents(), converted.data(),
                converted.size() * sizeof(AetherGaussianGpu));
    gaussians_ = std::move(*gaussians);
    projected_ = std::move(*projectedBuffer);
    tileCounts_ = std::move(*counts);
    offsets_ = std::move(*offsets);
    scanBlockSums_ = std::move(*scanBlockSums);
    gaussianCount_ = static_cast<std::uint32_t>(converted.size());
    return {};
}

Result<void> GaussianPipeline::ensureTileRanges(std::uint32_t tileCount) {
    if (tileCount <= rangeCapacity_)
        return {};
    auto ranges =
        makeBuffer(device_.get(), static_cast<std::size_t>(tileCount) * sizeof(simd_uint2),
                   MTL::ResourceStorageModePrivate, "Gaussian Tile Ranges");
    if (!ranges)
        return std::unexpected(ranges.error());
    ranges_ = std::move(*ranges);
    rangeCapacity_ = tileCount;
    return {};
}

Result<void>
GaussianPipeline::dispatch1D(MTL::CommandBuffer* commandBuffer, MTL::ComputePipelineState* pipeline,
                             std::uint32_t threads, const char* label,
                             const std::function<void(MTL::ComputeCommandEncoder*)>& bind) const {
    MTL::ComputeCommandEncoder* encoder = commandBuffer->computeCommandEncoder();
    if (!encoder)
        return fail(ErrorCode::metal, "Unable to create Gaussian compute encoder", label);
    encoder->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    encoder->setComputePipelineState(pipeline);
    bind(encoder);
    const NS::UInteger groupWidth =
        std::min<NS::UInteger>(pipeline->maxTotalThreadsPerThreadgroup(), 256);
    encoder->dispatchThreads(MTL::Size::Make(threads, 1, 1), MTL::Size::Make(groupWidth, 1, 1));
    encoder->endEncoding();
    return {};
}

Result<void> GaussianPipeline::encode(MTL::CommandBuffer* commandBuffer,
                                      AetherGaussianCamera camera, MTL::Texture* color,
                                      MTL::Texture* depth, MTL::Texture* ids) {
    if (!commandBuffer || !gaussians_ || !color || !depth || !ids || color->width() == 0 ||
        color->height() == 0 || depth->width() != color->width() ||
        depth->height() != color->height() || ids->width() != color->width() ||
        ids->height() != color->height() || depth->pixelFormat() != MTL::PixelFormatR32Float ||
        ids->pixelFormat() != MTL::PixelFormatR32Uint) {
        return fail(ErrorCode::invalidArgument, "Gaussian targets or loaded state are invalid");
    }
    if (color->width() > std::numeric_limits<std::uint32_t>::max() ||
        color->height() > std::numeric_limits<std::uint32_t>::max()) {
        return fail(ErrorCode::resourceExhausted, "Gaussian target dimensions exceed uint32");
    }
    const auto width = static_cast<std::uint32_t>(color->width());
    const auto height = static_cast<std::uint32_t>(color->height());
    const std::uint32_t tileColumns = (width + 15U) / 16U;
    const std::uint32_t tileRows = (height + 15U) / 16U;
    if (tileColumns > std::numeric_limits<std::uint32_t>::max() / tileRows)
        return fail(ErrorCode::resourceExhausted, "Gaussian tile grid overflows");
    const std::uint32_t tileCount = tileColumns * tileRows;
    if (auto result = ensureTileRanges(tileCount); !result)
        return result;
    camera.depthViewport.z = static_cast<float>(width);
    camera.depthViewport.w = static_cast<float>(height);
    camera.tileGridCounts = {tileColumns, tileRows, gaussianCount_, maximumTileEntries_};

    MTL::BlitCommandEncoder* clear = commandBuffer->blitCommandEncoder();
    if (!clear)
        return fail(ErrorCode::metal, "Unable to create Gaussian counter clear encoder");
    clear->setLabel(NS::String::string("Gaussian Counter Clear", NS::UTF8StringEncoding));
    clear->fillBuffer(counters_.get(), NS::Range::Make(0, sizeof(AetherGaussianCounters)), 0);
    clear->endEncoding();

    if (auto result = dispatch1D(commandBuffer, pipelines_[project].get(), gaussianCount_,
                                 "Gaussian Projection",
                                 [&](MTL::ComputeCommandEncoder* encoder) {
                                     encoder->setBuffer(gaussians_.get(), 0, 0);
                                     encoder->setBytes(&camera, sizeof(camera), 1);
                                     encoder->setBuffer(projected_.get(), 0, 2);
                                     encoder->setBuffer(counters_.get(), 0, 3);
                                     encoder->setBuffer(tileCounts_.get(), 0, 4);
                                 });
        !result)
        return result;
    const bool parallelScan = pipelines_[scanBlocks]->maxTotalThreadsPerThreadgroup() >= 256;
    if (parallelScan) {
        MTL::ComputeCommandEncoder* scanEncoder = commandBuffer->computeCommandEncoder();
        if (!scanEncoder)
            return fail(ErrorCode::metal, "Unable to create Gaussian block-scan encoder");
        scanEncoder->setLabel(NS::String::string("Gaussian Block Scan", NS::UTF8StringEncoding));
        scanEncoder->setComputePipelineState(pipelines_[scanBlocks].get());
        scanEncoder->setBuffer(tileCounts_.get(), 0, 0);
        scanEncoder->setBuffer(offsets_.get(), 0, 1);
        scanEncoder->setBuffer(scanBlockSums_.get(), 0, 2);
        scanEncoder->setBytes(&camera, sizeof(camera), 3);
        const std::uint32_t scanBlockCount = (gaussianCount_ + 255U) / 256U;
        scanEncoder->dispatchThreadgroups(MTL::Size::Make(scanBlockCount, 1, 1),
                                          MTL::Size::Make(256, 1, 1));
        scanEncoder->endEncoding();
        if (auto result = dispatch1D(commandBuffer, pipelines_[scanBlockSums].get(), 1,
                                     "Gaussian Block Prefix",
                                     [&](MTL::ComputeCommandEncoder* encoder) {
                                         encoder->setBuffer(scanBlockSums_.get(), 0, 0);
                                         encoder->setBuffer(counters_.get(), 0, 1);
                                         encoder->setBytes(&camera, sizeof(camera), 2);
                                         encoder->setBuffer(indirectDispatch_.get(), 0, 3);
                                     });
            !result)
            return result;
        if (auto result = dispatch1D(commandBuffer, pipelines_[addBlockOffsets].get(),
                                     gaussianCount_, "Gaussian Block Offset Propagation",
                                     [&](MTL::ComputeCommandEncoder* encoder) {
                                         encoder->setBuffer(offsets_.get(), 0, 0);
                                         encoder->setBuffer(scanBlockSums_.get(), 0, 1);
                                         encoder->setBytes(&camera, sizeof(camera), 2);
                                     });
            !result)
            return result;
    } else if (auto result = dispatch1D(commandBuffer, pipelines_[serialScan].get(), 1,
                                        "Gaussian Serial Scan Fallback",
                                        [&](MTL::ComputeCommandEncoder* encoder) {
                                            encoder->setBuffer(tileCounts_.get(), 0, 0);
                                            encoder->setBuffer(offsets_.get(), 0, 1);
                                            encoder->setBuffer(counters_.get(), 0, 2);
                                            encoder->setBytes(&camera, sizeof(camera), 3);
                                            encoder->setBuffer(indirectDispatch_.get(), 0, 4);
                                        });
               !result) {
        return result;
    }
    if (auto result = dispatch1D(commandBuffer, pipelines_[generateKeys].get(), gaussianCount_,
                                 "Gaussian Key Generation",
                                 [&](MTL::ComputeCommandEncoder* encoder) {
                                     encoder->setBuffer(projected_.get(), 0, 0);
                                     encoder->setBuffer(offsets_.get(), 0, 1);
                                     encoder->setBuffer(keysA_.get(), 0, 2);
                                     encoder->setBuffer(valuesA_.get(), 0, 3);
                                     encoder->setBytes(&camera, sizeof(camera), 4);
                                 });
        !result)
        return result;

    // The responsive Studio shader packs {tile, quantized positive depth} into key.x while keeping
    // the exact tile ID in key.y. During reduced-density preview this lets us sort one 32-bit key
    // instead of the full 64-bit {depth,tile} pair. Eight 4-bit parallel passes (or four 8-bit
    // serial passes) therefore preserve tile grouping + front-to-back order at half the radix work.
    // The default 240k budget keeps the canonical/full path on the original 64-bit sort.
    constexpr std::uint32_t compactSortTileLimit = 1U << 18U;
    const std::uint32_t currentBudget =
        responsiveGaussianViewportBudget.load(std::memory_order_relaxed);
    const bool compactPreviewSort = currentBudget < 240'000U && tileCount < compactSortTileLimit;

    const bool parallelRadix = pipelines_[radixHistogram]->maxTotalThreadsPerThreadgroup() >= 256 &&
                               pipelines_[radixScatter]->maxTotalThreadsPerThreadgroup() >= 256;
    if (parallelRadix) {
        const std::uint32_t passCount = compactPreviewSort ? 8U : 16U;
        for (std::uint32_t pass = 0; pass < passCount; ++pass) {
            const bool even = (pass % 2U) == 0;
            MTL::Buffer* inputKeys = even ? keysA_.get() : keysB_.get();
            MTL::Buffer* inputValues = even ? valuesA_.get() : valuesB_.get();
            MTL::Buffer* outputKeys = even ? keysB_.get() : keysA_.get();
            MTL::Buffer* outputValues = even ? valuesB_.get() : valuesA_.get();
            MTL::ComputeCommandEncoder* histogram = commandBuffer->computeCommandEncoder();
            if (!histogram)
                return fail(ErrorCode::metal, "Unable to create Gaussian radix histogram encoder");
            histogram->setLabel(
                NS::String::string("Gaussian Radix Histogram", NS::UTF8StringEncoding));
            histogram->setComputePipelineState(pipelines_[radixHistogram].get());
            histogram->setBuffer(inputKeys, 0, 0);
            histogram->setBuffer(radixHistograms_.get(), 0, 1);
            histogram->setBuffer(counters_.get(), 0, 2);
            histogram->setBytes(&pass, sizeof(pass), 3);
            histogram->dispatchThreadgroups(indirectDispatch_.get(), 0, MTL::Size::Make(256, 1, 1));
            histogram->endEncoding();
            if (auto result = dispatch1D(commandBuffer, pipelines_[radixOffsets].get(), 1,
                                         "Gaussian Radix Group Prefix",
                                         [&](MTL::ComputeCommandEncoder* encoder) {
                                             encoder->setBuffer(radixHistograms_.get(), 0, 0);
                                             encoder->setBuffer(radixGroupOffsets_.get(), 0, 1);
                                             encoder->setBuffer(counters_.get(), 0, 2);
                                         });
                !result)
                return result;
            MTL::ComputeCommandEncoder* scatter = commandBuffer->computeCommandEncoder();
            if (!scatter)
                return fail(ErrorCode::metal, "Unable to create Gaussian radix scatter encoder");
            scatter->setLabel(
                NS::String::string("Gaussian Radix Stable Scatter", NS::UTF8StringEncoding));
            scatter->setComputePipelineState(pipelines_[radixScatter].get());
            scatter->setBuffer(inputKeys, 0, 0);
            scatter->setBuffer(inputValues, 0, 1);
            scatter->setBuffer(outputKeys, 0, 2);
            scatter->setBuffer(outputValues, 0, 3);
            scatter->setBuffer(radixGroupOffsets_.get(), 0, 4);
            scatter->setBuffer(counters_.get(), 0, 5);
            scatter->setBytes(&pass, sizeof(pass), 6);
            scatter->dispatchThreadgroups(indirectDispatch_.get(), 0, MTL::Size::Make(256, 1, 1));
            scatter->endEncoding();
        }
    } else {
        const std::uint32_t passCount = compactPreviewSort ? 4U : 8U;
        for (std::uint32_t pass = 0; pass < passCount; ++pass) {
            const bool even = (pass % 2U) == 0;
            MTL::Buffer* inputKeys = even ? keysA_.get() : keysB_.get();
            MTL::Buffer* inputValues = even ? valuesA_.get() : valuesB_.get();
            MTL::Buffer* outputKeys = even ? keysB_.get() : keysA_.get();
            MTL::Buffer* outputValues = even ? valuesB_.get() : valuesA_.get();
            if (auto result = dispatch1D(commandBuffer, pipelines_[serialRadix].get(), 1,
                                         "Gaussian Serial Radix Fallback",
                                         [&](MTL::ComputeCommandEncoder* encoder) {
                                             encoder->setBuffer(inputKeys, 0, 0);
                                             encoder->setBuffer(inputValues, 0, 1);
                                             encoder->setBuffer(outputKeys, 0, 2);
                                             encoder->setBuffer(outputValues, 0, 3);
                                             encoder->setBuffer(counters_.get(), 0, 4);
                                             encoder->setBytes(&pass, sizeof(pass), 5);
                                         });
                !result)
                return result;
        }
    }

    if (auto result = dispatch1D(commandBuffer, pipelines_[initializeRanges].get(), tileCount,
                                 "Gaussian Range Initialization",
                                 [&](MTL::ComputeCommandEncoder* encoder) {
                                     encoder->setBuffer(ranges_.get(), 0, 0);
                                     encoder->setBytes(&camera, sizeof(camera), 1);
                                 });
        !result)
        return result;
    if (auto result = dispatch1D(commandBuffer, pipelines_[buildRanges].get(), 1,
                                 "Gaussian Range Construction",
                                 [&](MTL::ComputeCommandEncoder* encoder) {
                                     encoder->setBuffer(keysA_.get(), 0, 0);
                                     encoder->setBuffer(ranges_.get(), 0, 1);
                                     encoder->setBuffer(counters_.get(), 0, 2);
                                 });
        !result)
        return result;

    MTL::ComputeCommandEncoder* encoder = commandBuffer->computeCommandEncoder();
    if (!encoder)
        return fail(ErrorCode::metal, "Unable to create Gaussian composite encoder");
    encoder->setLabel(NS::String::string("Gaussian Tile Composite", NS::UTF8StringEncoding));
    encoder->setComputePipelineState(pipelines_[composite].get());
    encoder->setBuffer(projected_.get(), 0, 0);
    encoder->setBuffer(valuesA_.get(), 0, 1);
    encoder->setBuffer(ranges_.get(), 0, 2);
    encoder->setBuffer(counters_.get(), 0, 3);
    encoder->setBytes(&camera, sizeof(camera), 4);
    encoder->setTexture(color, 0);
    encoder->setTexture(depth, 1);
    encoder->setTexture(ids, 2);
    encoder->dispatchThreads(MTL::Size::Make(width, height, 1), MTL::Size::Make(8, 8, 1));
    encoder->endEncoding();
    return {};
}

GaussianPipelineStatistics GaussianPipeline::statistics() const noexcept {
    if (!counters_ || !counters_->contents())
        return {};
    AetherGaussianCounters counters{};
    std::memcpy(&counters, counters_->contents(), sizeof(counters));
    return {counters.visibleGaussians, counters.tileEntries, counters.overflowedEntries,
            counters.earlyTerminations};
}

} // namespace aether::metal
