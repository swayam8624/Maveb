#include <aether/metal/SparseMetalTsdfVolume.hpp>

#include <shared/AetherShaderTypes.h>

#include <Foundation/Foundation.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <span>
#include <string>
#include <utility>

namespace aether::metal {
namespace {

constexpr std::size_t gpuVoxelBytes = sizeof(AetherTsdfVoxelGpu);

Result<std::size_t> checkedProduct(std::size_t left, std::size_t right, const char* context) {
    if (left == 0 || right == 0 || left > std::numeric_limits<std::size_t>::max() / right)
        return fail(ErrorCode::resourceExhausted, "Sparse Metal TSDF size overflows", context);
    return left * right;
}

Result<MetalPtr<MTL::Buffer>> makeBuffer(MTL::Device* device, std::size_t bytes,
                                         MTL::ResourceOptions options, const char* label) {
    if (!device || bytes == 0 || bytes > device->maxBufferLength())
        return fail(ErrorCode::resourceExhausted, "Sparse Metal TSDF buffer exceeds device limits",
                    label);
    auto buffer = adopt(device->newBuffer(bytes, options));
    if (!buffer)
        return fail(ErrorCode::resourceExhausted, "Sparse Metal TSDF buffer allocation failed",
                    label);
    buffer->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    return buffer;
}

template <typename Value>
Result<MetalPtr<MTL::Buffer>> makeSharedBuffer(MTL::Device* device, std::span<const Value> values,
                                               const char* label) {
    auto bytes = checkedProduct(values.size(), sizeof(Value), label);
    if (!bytes)
        return std::unexpected(bytes.error());
    auto buffer = makeBuffer(device, *bytes, MTL::ResourceStorageModeShared, label);
    if (!buffer)
        return std::unexpected(buffer.error());
    std::memcpy((*buffer)->contents(), values.data(), *bytes);
    return buffer;
}

Result<void> complete(MTL::CommandBuffer* commandBuffer, const char* label) {
    if (!commandBuffer)
        return fail(ErrorCode::metal, "Unable to allocate Sparse Metal TSDF command buffer", label);
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() != MTL::CommandBufferStatusCompleted) {
        const auto* error = commandBuffer->error();
        const std::string context = error && error->localizedDescription()
                                        ? error->localizedDescription()->utf8String()
                                        : label;
        return fail(ErrorCode::metal, "Sparse Metal TSDF command buffer failed", context);
    }
    return {};
}

Result<void> encodeDispatch(MTL::CommandBuffer* commandBuffer, MTL::ComputePipelineState* pipeline,
                            std::size_t threads, const char* label, const auto& bindResources) {
    if (!commandBuffer || !pipeline || threads == 0)
        return fail(ErrorCode::invalidArgument, "Sparse Metal TSDF dispatch is invalid", label);
    auto* encoder = commandBuffer->computeCommandEncoder();
    if (!encoder)
        return fail(ErrorCode::metal, "Unable to create Sparse Metal TSDF encoder", label);
    encoder->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    encoder->setComputePipelineState(pipeline);
    bindResources(encoder);
    const auto groupWidth = std::min<NS::UInteger>(pipeline->maxTotalThreadsPerThreadgroup(), 256);
    encoder->dispatchThreads(MTL::Size::Make(threads, 1, 1), MTL::Size::Make(groupWidth, 1, 1));
    encoder->endEncoding();
    return {};
}

float readDepth(const capture::ImagePlane& plane, std::uint32_t x, std::uint32_t y) {
    float value{};
    const auto* row = plane.buffer.data + static_cast<std::size_t>(y) * plane.rowStrideBytes;
    std::memcpy(&value, row + static_cast<std::size_t>(x) * sizeof(float), sizeof(float));
    return value;
}

float readConfidence(const capture::ImagePlane* plane, std::uint32_t x, std::uint32_t y) {
    if (!plane)
        return 1.0F;
    const auto* row = plane->buffer.data + static_cast<std::size_t>(y) * plane->rowStrideBytes;
    return static_cast<float>(std::to_integer<std::uint8_t>(row[x])) / 255.0F;
}

simd_float4 readColor(const capture::CapturePacket& packet, std::uint32_t x, std::uint32_t y) {
    if (packet.colorPlanes.empty() || !packet.colorPlanes.front().valid() ||
        packet.calibration.width == 0 || packet.calibration.height == 0)
        return {};
    const auto& plane = packet.colorPlanes.front();
    const auto colorX = std::min<std::uint32_t>(
        plane.width - 1, static_cast<std::uint32_t>(static_cast<std::uint64_t>(x) * plane.width /
                                                    packet.calibration.width));
    const auto colorY = std::min<std::uint32_t>(
        plane.height - 1, static_cast<std::uint32_t>(static_cast<std::uint64_t>(y) * plane.height /
                                                     packet.calibration.height));
    const auto* row = plane.buffer.data + static_cast<std::size_t>(colorY) * plane.rowStrideBytes;
    switch (plane.format) {
    case capture::PixelFormat::gray8: {
        const float value = static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) / 255.0F;
        return {value, value, value, 1.0F};
    }
    case capture::PixelFormat::rgb8: {
        const auto* pixel = row + static_cast<std::size_t>(colorX) * 3;
        return {static_cast<float>(std::to_integer<std::uint8_t>(pixel[0])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[1])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[2])) / 255.0F, 1.0F};
    }
    case capture::PixelFormat::bgra8: {
        const auto* pixel = row + static_cast<std::size_t>(colorX) * 4;
        return {static_cast<float>(std::to_integer<std::uint8_t>(pixel[2])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[1])) / 255.0F,
                static_cast<float>(std::to_integer<std::uint8_t>(pixel[0])) / 255.0F, 1.0F};
    }
    case capture::PixelFormat::yuv420BiPlanarVideoRange: {
        if (packet.colorPlanes.size() != 2 || !packet.colorPlanes[1].valid())
            return {};
        const auto& chroma = packet.colorPlanes[1];
        const auto chromaX = std::min<std::uint32_t>(chroma.width - 1, colorX / 2);
        const auto chromaY = std::min<std::uint32_t>(chroma.height - 1, colorY / 2);
        const auto* chromaRow =
            chroma.buffer.data + static_cast<std::size_t>(chromaY) * chroma.rowStrideBytes;
        const auto* chromaPixel = chromaRow + static_cast<std::size_t>(chromaX) * 2;
        const float luminance = std::clamp(
            (static_cast<float>(std::to_integer<std::uint8_t>(row[colorX])) - 16.0F) / 219.0F, 0.0F,
            1.0F);
        const float cb =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[0])) - 128.0F) / 224.0F;
        const float cr =
            (static_cast<float>(std::to_integer<std::uint8_t>(chromaPixel[1])) - 128.0F) / 224.0F;
        return {std::clamp(luminance + 1.5748F * cr, 0.0F, 1.0F),
                std::clamp(luminance - 0.1873F * cb - 0.4681F * cr, 0.0F, 1.0F),
                std::clamp(luminance + 1.8556F * cb, 0.0F, 1.0F), 1.0F};
    }
    default:
        return {};
    }
}

struct FrameBuffers final {
    MetalPtr<MTL::Buffer> blocks;
    MetalPtr<MTL::Buffer> depth;
    MetalPtr<MTL::Buffer> confidence;
    MetalPtr<MTL::Buffer> color;
};

Result<FrameBuffers>
makeFrameBuffers(MTL::Device* device, const capture::CapturePacket& packet,
                 const reconstruction::DepthObservation& observation,
                 std::span<const reconstruction::TsdfBlockCoordinate> candidates,
                 std::size_t maximumFramePixels) {
    const auto pixelCountResult = checkedProduct(observation.depthMetres.width,
                                                 observation.depthMetres.height, "frame pixels");
    if (!pixelCountResult || *pixelCountResult > std::numeric_limits<std::uint32_t>::max() ||
        *pixelCountResult > maximumFramePixels)
        return fail(ErrorCode::resourceExhausted, "Sparse Metal TSDF frame dimensions overflow");
    const auto pixelCount = *pixelCountResult;
    std::vector<float> depths(pixelCount);
    std::vector<float> confidences(pixelCount);
    std::vector<simd_float4> colors(pixelCount);
    for (std::uint32_t y = 0; y < observation.depthMetres.height; ++y)
        for (std::uint32_t x = 0; x < observation.depthMetres.width; ++x) {
            const auto index = static_cast<std::size_t>(y) * observation.depthMetres.width + x;
            depths[index] = readDepth(observation.depthMetres, x, y);
            confidences[index] = readConfidence(observation.confidence, x, y);
            colors[index] = readColor(packet, x, y);
        }
    std::vector<simd_uint4> blocks;
    blocks.reserve(candidates.size());
    for (const auto coordinate : candidates)
        blocks.push_back(simd_uint4{coordinate.x, coordinate.y, coordinate.z, 0U});
    auto blockBuffer = makeSharedBuffer(device, std::span<const simd_uint4>(blocks),
                                        "Sparse TSDF Candidate Blocks");
    auto depthBuffer =
        makeSharedBuffer(device, std::span<const float>(depths), "Sparse TSDF Depth");
    auto confidenceBuffer =
        makeSharedBuffer(device, std::span<const float>(confidences), "Sparse TSDF Confidence");
    auto colorBuffer =
        makeSharedBuffer(device, std::span<const simd_float4>(colors), "Sparse TSDF Color");
    if (!blockBuffer)
        return std::unexpected(blockBuffer.error());
    if (!depthBuffer)
        return std::unexpected(depthBuffer.error());
    if (!confidenceBuffer)
        return std::unexpected(confidenceBuffer.error());
    if (!colorBuffer)
        return std::unexpected(colorBuffer.error());
    return FrameBuffers{std::move(*blockBuffer), std::move(*depthBuffer),
                        std::move(*confidenceBuffer), std::move(*colorBuffer)};
}

AetherTsdfFrameUniforms makeUniforms(const reconstruction::SparseTsdfConfig& config,
                                     const capture::CapturePacket& packet,
                                     const reconstruction::PoseEstimate& pose,
                                     const reconstruction::DepthObservation& depth,
                                     std::uint32_t candidateCount, std::uint32_t voxelsPerBlock) {
    const auto& cameraToWorld = pose.cameraToWorld;
    AetherTsdfFrameUniforms uniforms{};
    uniforms.originVoxelSize = {static_cast<float>(config.volume.originMetres[0]),
                                static_cast<float>(config.volume.originMetres[1]),
                                static_cast<float>(config.volume.originMetres[2]),
                                static_cast<float>(config.volume.voxelSizeMetres)};
    uniforms.truncationDepthWeight = {static_cast<float>(config.volume.truncationDistanceMetres),
                                      static_cast<float>(config.volume.minimumDepthMetres),
                                      static_cast<float>(config.volume.maximumDepthMetres),
                                      static_cast<float>(config.volume.maximumWeight)};
    uniforms.intrinsics = {
        static_cast<float>(packet.calibration.fx), static_cast<float>(packet.calibration.fy),
        static_cast<float>(packet.calibration.cx), static_cast<float>(packet.calibration.cy)};
    uniforms.cameraTranslationDepthScale = {static_cast<float>(cameraToWorld.translation[0]),
                                            static_cast<float>(cameraToWorld.translation[1]),
                                            static_cast<float>(cameraToWorld.translation[2]),
                                            static_cast<float>(depth.scaleMetresPerUnit)};
    uniforms.worldToCameraQuaternion = {static_cast<float>(cameraToWorld.orientation[0]),
                                        static_cast<float>(-cameraToWorld.orientation[1]),
                                        static_cast<float>(-cameraToWorld.orientation[2]),
                                        static_cast<float>(-cameraToWorld.orientation[3])};
    uniforms.confidence = {static_cast<float>(pose.confidence),
                           static_cast<float>(depth.confidenceFloor),
                           depth.confidence ? 1.0F : 0.0F, 0.0F};
    uniforms.gridDimensionsBlock = {config.volume.dimensions[0], config.volume.dimensions[1],
                                    config.volume.dimensions[2], config.blockResolution};
    uniforms.imageCandidates = {depth.depthMetres.width, depth.depthMetres.height, candidateCount,
                                voxelsPerBlock};
    return uniforms;
}

} // namespace

SparseMetalTsdfVolume::SparseMetalTsdfVolume(MTL::Device* device,
                                             reconstruction::SparseTsdfConfig config,
                                             SparseMetalTsdfLimits limits)
    : config_(config), limits_(limits), device_(retain(device)) {}

Result<std::unique_ptr<SparseMetalTsdfVolume>>
SparseMetalTsdfVolume::create(MTL::Device* device, MTL::Library* library,
                              reconstruction::SparseTsdfConfig config,
                              SparseMetalTsdfLimits limits) {
    if (!device || !library)
        return fail(ErrorCode::invalidArgument, "Sparse Metal TSDF creation arguments are invalid");
    auto validated = reconstruction::SparseTsdfVolume::create(config);
    if (!validated)
        return std::unexpected(validated.error());
    if (limits.maximumFramePixels == 0 || limits.maximumResidentBytes == 0 ||
        limits.maximumScratchBytes == 0)
        return fail(ErrorCode::invalidArgument,
                    "Sparse Metal TSDF memory limits must all be greater than zero");
    auto result =
        std::unique_ptr<SparseMetalTsdfVolume>(new SparseMetalTsdfVolume(device, config, limits));
    result->commandQueue_ = adopt(device->newCommandQueue());
    if (!result->commandQueue_)
        return fail(ErrorCode::metal, "Unable to create Sparse Metal TSDF command queue");
    result->commandQueue_->setLabel(
        NS::String::string("Sparse TSDF Fusion Queue", NS::UTF8StringEncoding));
    if (auto built = result->buildPipelines(library); !built)
        return std::unexpected(built.error());
    return result;
}

Result<void> SparseMetalTsdfVolume::buildPipelines(MTL::Library* library) {
    const auto build = [&](const char* name) -> Result<MetalPtr<MTL::ComputePipelineState>> {
        auto function =
            adopt(library->newFunction(NS::String::string(name, NS::UTF8StringEncoding)));
        if (!function)
            return fail(ErrorCode::metal, "Offline library is missing a Sparse TSDF kernel", name);
        NS::Error* error = nullptr;
        auto pipeline = adopt(device_->newComputePipelineState(function.get(), &error));
        if (!pipeline) {
            const std::string context = error && error->localizedDescription()
                                            ? error->localizedDescription()->utf8String()
                                            : name;
            return fail(ErrorCode::metal, "Unable to create Sparse TSDF compute pipeline", context);
        }
        return pipeline;
    };
    auto classify = build("aetherSparseTsdfClassify");
    auto initialize = build("aetherSparseTsdfInitialize");
    auto integrate = build("aetherSparseTsdfIntegrate");
    if (!classify)
        return std::unexpected(classify.error());
    if (!initialize)
        return std::unexpected(initialize.error());
    if (!integrate)
        return std::unexpected(integrate.error());
    classifyPipeline_ = std::move(*classify);
    initializePipeline_ = std::move(*initialize);
    integratePipeline_ = std::move(*integrate);
    return {};
}

Result<void> SparseMetalTsdfVolume::ensureResidentCapacity(std::size_t requiredBlocks) {
    if (requiredBlocks <= residentCapacityBlocks_)
        return {};
    std::size_t capacity = std::max<std::size_t>(1, residentCapacityBlocks_);
    while (capacity < requiredBlocks) {
        const auto doubled =
            capacity > config_.maximumBlocks / 2 ? config_.maximumBlocks : capacity * 2;
        if (doubled <= capacity)
            return fail(ErrorCode::resourceExhausted,
                        "Sparse Metal TSDF resident capacity cannot grow further");
        capacity = doubled;
    }
    const std::size_t voxelsPerBlock = static_cast<std::size_t>(config_.blockResolution) *
                                       config_.blockResolution * config_.blockResolution;
    auto voxelCount = checkedProduct(capacity, voxelsPerBlock, "resident voxel capacity");
    if (!voxelCount || *voxelCount > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::resourceExhausted,
                    "Sparse Metal TSDF resident capacity exceeds uint32 dispatch limits");
    auto bytes = checkedProduct(*voxelCount, gpuVoxelBytes, "resident voxel bytes");
    if (!bytes)
        return std::unexpected(bytes.error());
    if (*bytes > limits_.maximumResidentBytes)
        return fail(ErrorCode::resourceExhausted,
                    "Sparse Metal TSDF resident allocation exceeds its byte budget");
    auto replacement = makeBuffer(device_.get(), *bytes, MTL::ResourceStorageModePrivate,
                                  "Sparse TSDF Resident Voxels");
    if (!replacement)
        return std::unexpected(replacement.error());
    auto* command = commandQueue_->commandBuffer();
    const auto count = static_cast<std::uint32_t>(*voxelCount);
    if (auto encoded = encodeDispatch(command, initializePipeline_.get(), *voxelCount,
                                      "Sparse TSDF Resident Initialize",
                                      [&](MTL::ComputeCommandEncoder* encoder) {
                                          encoder->setBuffer(replacement->get(), 0, 0);
                                          encoder->setBytes(&count, sizeof(count), 1);
                                      });
        !encoded)
        return encoded;
    if (residentVoxels_ && !slotCoordinates_.empty()) {
        auto usedVoxels =
            checkedProduct(slotCoordinates_.size(), voxelsPerBlock, "resident used voxel count");
        auto usedBytes =
            usedVoxels ? checkedProduct(*usedVoxels, gpuVoxelBytes, "resident used voxel bytes")
                       : Result<std::size_t>(std::unexpected(usedVoxels.error()));
        if (!usedBytes)
            return std::unexpected(usedBytes.error());
        auto* blit = command->blitCommandEncoder();
        if (!blit)
            return fail(ErrorCode::metal, "Unable to create Sparse TSDF capacity-copy encoder");
        blit->setLabel(NS::String::string("Sparse TSDF Capacity Copy", NS::UTF8StringEncoding));
        blit->copyFromBuffer(residentVoxels_.get(), 0, replacement->get(), 0, *usedBytes);
        blit->endEncoding();
    }
    if (auto completed = complete(command, "resident capacity growth"); !completed)
        return completed;
    residentVoxels_ = std::move(*replacement);
    residentCapacityBlocks_ = capacity;
    return {};
}

Result<void> SparseMetalTsdfVolume::integrate(const capture::CapturePacket& packet,
                                              const reconstruction::PoseEstimate& pose,
                                              const reconstruction::DepthObservation& depth) {
    auto candidateResult =
        reconstruction::SparseTsdfVolume::candidateBlocks(config_, packet, pose, depth);
    if (!candidateResult)
        return std::unexpected(candidateResult.error());
    const auto& candidates = *candidateResult;
    const std::size_t voxelsPerBlock = static_cast<std::size_t>(config_.blockResolution) *
                                       config_.blockResolution * config_.blockResolution;
    auto classificationThreads =
        checkedProduct(candidates.size(), voxelsPerBlock, "candidate classification threads");
    if (!classificationThreads ||
        *classificationThreads > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::resourceExhausted,
                    "Sparse Metal TSDF candidate dispatch exceeds uint32 limits");
    auto frameBuffers =
        makeFrameBuffers(device_.get(), packet, depth, candidates, limits_.maximumFramePixels);
    if (!frameBuffers)
        return std::unexpected(frameBuffers.error());
    std::vector<std::uint32_t> zeroCounts(candidates.size());
    auto counts = makeSharedBuffer(device_.get(), std::span<const std::uint32_t>(zeroCounts),
                                   "Sparse TSDF Candidate Update Counts");
    if (!counts)
        return std::unexpected(counts.error());
    auto uniforms =
        makeUniforms(config_, packet, pose, depth, static_cast<std::uint32_t>(candidates.size()),
                     static_cast<std::uint32_t>(voxelsPerBlock));
    auto* classification = commandQueue_->commandBuffer();
    if (auto encoded =
            encodeDispatch(classification, classifyPipeline_.get(), *classificationThreads,
                           "Sparse TSDF Candidate Classification",
                           [&](MTL::ComputeCommandEncoder* encoder) {
                               encoder->setBuffer(frameBuffers->blocks.get(), 0, 0);
                               encoder->setBuffer(frameBuffers->depth.get(), 0, 1);
                               encoder->setBuffer(frameBuffers->confidence.get(), 0, 2);
                               encoder->setBuffer(frameBuffers->color.get(), 0, 3);
                               encoder->setBuffer(counts->get(), 0, 4);
                               encoder->setBytes(&uniforms, sizeof(uniforms), 5);
                           });
        !encoded)
        return encoded;
    if (auto completed = complete(classification, "candidate classification"); !completed)
        return completed;

    const auto* classified = static_cast<const std::uint32_t*>((*counts)->contents());
    std::vector<reconstruction::TsdfBlockCoordinate> updateBlocks;
    std::size_t updateCount{};
    updateBlocks.reserve(candidates.size());
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        if (classified[index] > 0)
            updateBlocks.push_back(candidates[index]);
        updateCount += classified[index];
    }
    if (updateBlocks.empty() || updateCount == 0)
        return fail(ErrorCode::invalidArgument,
                    "Depth frame did not observe any voxel in the configured Sparse Metal volume",
                    std::to_string(packet.frameId));
    std::size_t newBlocks{};
    for (const auto coordinate : updateBlocks)
        if (!blockSlots_.contains(coordinate))
            ++newBlocks;
    if (newBlocks > config_.maximumBlocks - blockSlots_.size())
        return fail(ErrorCode::resourceExhausted,
                    "Sparse Metal TSDF integration exceeds its resident block budget");
    auto scratchVoxelCount =
        checkedProduct(updateBlocks.size(), voxelsPerBlock, "scratch voxel count");
    auto scratchBytes = scratchVoxelCount
                            ? checkedProduct(*scratchVoxelCount, gpuVoxelBytes, "scratch bytes")
                            : Result<std::size_t>(std::unexpected(scratchVoxelCount.error()));
    if (!scratchBytes || *scratchVoxelCount > std::numeric_limits<std::uint32_t>::max())
        return fail(ErrorCode::resourceExhausted, "Sparse Metal TSDF scratch storage overflows");
    if (*scratchBytes > limits_.maximumScratchBytes)
        return fail(ErrorCode::resourceExhausted,
                    "Sparse Metal TSDF scratch allocation exceeds its byte budget");
    const std::size_t requiredBlocks = blockSlots_.size() + newBlocks;
    if (auto capacity = ensureResidentCapacity(requiredBlocks); !capacity)
        return capacity;
    auto scratch = makeBuffer(device_.get(), *scratchBytes, MTL::ResourceStorageModePrivate,
                              "Sparse TSDF Frame Scratch");
    if (!scratch)
        return std::unexpected(scratch.error());
    std::vector<simd_uint4> updateCoordinates;
    updateCoordinates.reserve(updateBlocks.size());
    for (std::size_t index = 0; index < updateBlocks.size(); ++index) {
        const auto coordinate = updateBlocks[index];
        updateCoordinates.push_back(simd_uint4{coordinate.x, coordinate.y, coordinate.z,
                                               static_cast<std::uint32_t>(index)});
    }
    auto updateCoordinatesBuffer = makeSharedBuffer(
        device_.get(), std::span<const simd_uint4>(updateCoordinates), "Sparse TSDF Update Blocks");
    if (!updateCoordinatesBuffer)
        return std::unexpected(updateCoordinatesBuffer.error());
    std::vector<std::uint32_t> newObservedZero(updateBlocks.size());
    auto newObserved =
        makeSharedBuffer(device_.get(), std::span<const std::uint32_t>(newObservedZero),
                         "Sparse TSDF New Observed Counts");
    if (!newObserved)
        return std::unexpected(newObserved.error());

    auto* prepare = commandQueue_->commandBuffer();
    const auto scratchCount = static_cast<std::uint32_t>(*scratchVoxelCount);
    if (auto encoded = encodeDispatch(prepare, initializePipeline_.get(), *scratchVoxelCount,
                                      "Sparse TSDF Scratch Initialize",
                                      [&](MTL::ComputeCommandEncoder* encoder) {
                                          encoder->setBuffer(scratch->get(), 0, 0);
                                          encoder->setBytes(&scratchCount, sizeof(scratchCount), 1);
                                      });
        !encoded)
        return encoded;
    auto* copyExisting = prepare->blitCommandEncoder();
    if (!copyExisting)
        return fail(ErrorCode::metal, "Unable to create Sparse TSDF scratch-copy encoder");
    copyExisting->setLabel(
        NS::String::string("Sparse TSDF Existing Block Snapshot", NS::UTF8StringEncoding));
    const std::size_t blockBytes = voxelsPerBlock * gpuVoxelBytes;
    for (std::size_t index = 0; index < updateBlocks.size(); ++index)
        if (const auto existing = blockSlots_.find(updateBlocks[index]);
            existing != blockSlots_.end())
            copyExisting->copyFromBuffer(residentVoxels_.get(),
                                         static_cast<std::size_t>(existing->second) * blockBytes,
                                         scratch->get(), index * blockBytes, blockBytes);
    copyExisting->endEncoding();
    if (auto completed = complete(prepare, "scratch preparation"); !completed)
        return completed;

    uniforms.imageCandidates.z = static_cast<std::uint32_t>(updateBlocks.size());
    auto* fusion = commandQueue_->commandBuffer();
    if (auto encoded = encodeDispatch(fusion, integratePipeline_.get(), *scratchVoxelCount,
                                      "Sparse TSDF Voxel Fusion",
                                      [&](MTL::ComputeCommandEncoder* encoder) {
                                          encoder->setBuffer(updateCoordinatesBuffer->get(), 0, 0);
                                          encoder->setBuffer(frameBuffers->depth.get(), 0, 1);
                                          encoder->setBuffer(frameBuffers->confidence.get(), 0, 2);
                                          encoder->setBuffer(frameBuffers->color.get(), 0, 3);
                                          encoder->setBuffer(scratch->get(), 0, 4);
                                          encoder->setBuffer(newObserved->get(), 0, 5);
                                          encoder->setBytes(&uniforms, sizeof(uniforms), 6);
                                      });
        !encoded)
        return encoded;
    if (auto completed = complete(fusion, "voxel fusion"); !completed)
        return completed;

    std::vector<std::uint32_t> destinationSlots;
    destinationSlots.reserve(updateBlocks.size());
    std::size_t nextSlot = slotCoordinates_.size();
    for (const auto coordinate : updateBlocks) {
        if (const auto existing = blockSlots_.find(coordinate); existing != blockSlots_.end())
            destinationSlots.push_back(existing->second);
        else
            destinationSlots.push_back(static_cast<std::uint32_t>(nextSlot++));
    }
    auto* publish = commandQueue_->commandBuffer();
    auto* copyPublished = publish ? publish->blitCommandEncoder() : nullptr;
    if (!copyPublished)
        return fail(ErrorCode::metal, "Unable to create Sparse TSDF publish encoder");
    copyPublished->setLabel(NS::String::string("Sparse TSDF Publish", NS::UTF8StringEncoding));
    for (std::size_t index = 0; index < updateBlocks.size(); ++index)
        copyPublished->copyFromBuffer(
            scratch->get(), index * blockBytes, residentVoxels_.get(),
            static_cast<std::size_t>(destinationSlots[index]) * blockBytes, blockBytes);
    copyPublished->endEncoding();
    if (auto completed = complete(publish, "block publication"); !completed)
        return completed;

    const auto* observedCounts = static_cast<const std::uint32_t*>((*newObserved)->contents());
    for (std::size_t index = 0; index < updateBlocks.size(); ++index) {
        const auto coordinate = updateBlocks[index];
        if (!blockSlots_.contains(coordinate)) {
            blockSlots_.emplace(coordinate, destinationSlots[index]);
            slotCoordinates_.push_back(coordinate);
        }
        dirtyBlocks_.insert(coordinate);
        observedVoxels_ += observedCounts[index];
    }
    ++integratedFrames_;
    ++generation_;
    lastFrameCandidateBlocks_ = candidates.size();
    lastFrameVoxelUpdates_ = updateCount;
    return {};
}

Result<SparseMetalTsdfSnapshot> SparseMetalTsdfVolume::snapshot() const {
    if (!residentVoxels_ || slotCoordinates_.empty())
        return fail(ErrorCode::notFound, "Sparse Metal TSDF contains no resident blocks");
    const std::size_t voxelsPerBlock = static_cast<std::size_t>(config_.blockResolution) *
                                       config_.blockResolution * config_.blockResolution;
    auto voxelCount = checkedProduct(slotCoordinates_.size(), voxelsPerBlock, "snapshot voxels");
    auto bytes = voxelCount ? checkedProduct(*voxelCount, gpuVoxelBytes, "snapshot bytes")
                            : Result<std::size_t>(std::unexpected(voxelCount.error()));
    if (!bytes)
        return std::unexpected(bytes.error());
    auto readback = makeBuffer(device_.get(), *bytes, MTL::ResourceStorageModeShared,
                               "Sparse TSDF Snapshot Readback");
    if (!readback)
        return std::unexpected(readback.error());
    auto* command = commandQueue_->commandBuffer();
    auto* blit = command ? command->blitCommandEncoder() : nullptr;
    if (!blit)
        return fail(ErrorCode::metal, "Unable to create Sparse TSDF snapshot encoder");
    blit->setLabel(NS::String::string("Sparse TSDF Snapshot", NS::UTF8StringEncoding));
    blit->copyFromBuffer(residentVoxels_.get(), 0, readback->get(), 0, *bytes);
    blit->endEncoding();
    if (auto completed = complete(command, "snapshot readback"); !completed)
        return std::unexpected(completed.error());

    SparseMetalTsdfSnapshot result{config_, generation_, {}};
    result.blocks.reserve(slotCoordinates_.size());
    const auto* source = static_cast<const AetherTsdfVoxelGpu*>((*readback)->contents());
    for (std::size_t slot = 0; slot < slotCoordinates_.size(); ++slot) {
        SparseMetalTsdfBlockSnapshot block;
        block.coordinate = slotCoordinates_[slot];
        block.voxels.resize(voxelsPerBlock);
        for (std::size_t index = 0; index < voxelsPerBlock; ++index) {
            const auto& gpu = source[slot * voxelsPerBlock + index];
            block.voxels[index] = {gpu.distance,
                                   gpu.weight,
                                   {gpu.colorRed, gpu.colorGreen, gpu.colorBlue},
                                   gpu.observations};
        }
        result.blocks.push_back(std::move(block));
    }
    std::sort(result.blocks.begin(), result.blocks.end(), [](const auto& left, const auto& right) {
        return left.coordinate < right.coordinate;
    });
    return result;
}

SparseMetalTsdfStatistics SparseMetalTsdfVolume::statistics() const noexcept {
    const std::size_t voxelsPerBlock = static_cast<std::size_t>(config_.blockResolution) *
                                       config_.blockResolution * config_.blockResolution;
    return {.residentBlocks = blockSlots_.size(),
            .residentVoxels = blockSlots_.size() * voxelsPerBlock,
            .observedVoxels = observedVoxels_,
            .residentPayloadBytes = blockSlots_.size() * voxelsPerBlock * gpuVoxelBytes,
            .reservedPayloadBytes = residentCapacityBlocks_ * voxelsPerBlock * gpuVoxelBytes,
            .integratedFrames = integratedFrames_,
            .lastFrameCandidateBlocks = lastFrameCandidateBlocks_,
            .lastFrameVoxelUpdates = lastFrameVoxelUpdates_,
            .dirtyBlocks = dirtyBlocks_.size(),
            .generation = generation_};
}

std::vector<reconstruction::TsdfBlockCoordinate> SparseMetalTsdfVolume::dirtyBlocks() const {
    return {dirtyBlocks_.begin(), dirtyBlocks_.end()};
}

} // namespace aether::metal
