#include <aether/metal/Renderer.hpp>

#include <aether/core/Log.hpp>
#include <aether/core/Profiler.hpp>
#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/hybrid/ProxyMeshCodec.hpp>
#include <aether/mesh/Animation.hpp>
#include <aether/mesh/GltfLoader.hpp>
#include <aether/mesh/TransparentSort.hpp>
#include <aether/package/Package.hpp>
#include <aether/package/Sha256.hpp>
#include <aether/revision/RevisionPlanner.hpp>
#include <aether/scene/Camera.hpp>
#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>

#include <CoreGraphics/CoreGraphics.h>
#include <Foundation/Foundation.hpp>
#include <Foundation/NSBundle.hpp>
#include <Foundation/NSURL.hpp>
#include <ImageIO/ImageIO.h>
#include <QuartzCore/CAMetalDrawable.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <span>
#include <utility>

namespace aether::metal {
namespace {
struct DecodedImage final {
    std::size_t width{};
    std::size_t height{};
    std::vector<std::uint8_t> rgba;
};

float halton(std::uint64_t index, std::uint32_t base) {
    float result = 0.0F;
    float fraction = 1.0F;
    while (index > 0) {
        fraction /= static_cast<float>(base);
        result += fraction * static_cast<float>(index % base);
        index /= base;
    }
    return result;
}

Result<DecodedImage> decodeImage(std::span<const std::byte> encoded) {
    if (encoded.empty() ||
        encoded.size() > static_cast<std::size_t>(std::numeric_limits<CFIndex>::max()))
        return fail(ErrorCode::corruptData, "Encoded glTF image size is invalid");
    CFDataRef data =
        CFDataCreate(kCFAllocatorDefault, reinterpret_cast<const UInt8*>(encoded.data()),
                     static_cast<CFIndex>(encoded.size()));
    if (!data)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate glTF image data");
    CGImageSourceRef source = CGImageSourceCreateWithData(data, nullptr);
    CFRelease(data);
    if (!source)
        return fail(ErrorCode::corruptData, "ImageIO could not identify glTF image bytes");
    CGImageRef image = CGImageSourceCreateImageAtIndex(source, 0, nullptr);
    CFRelease(source);
    if (!image)
        return fail(ErrorCode::corruptData, "ImageIO could not decode glTF image");
    const std::size_t width = CGImageGetWidth(image);
    const std::size_t height = CGImageGetHeight(image);
    constexpr std::size_t maximumDimension = 16'384;
    constexpr std::size_t maximumPixels = 67'108'864;
    if (width == 0 || height == 0 || width > maximumDimension || height > maximumDimension ||
        width > maximumPixels / height ||
        width > std::numeric_limits<std::size_t>::max() / 4 / height) {
        CGImageRelease(image);
        return fail(ErrorCode::resourceExhausted, "Decoded glTF image dimensions are unsafe");
    }
    DecodedImage result{width, height, std::vector<std::uint8_t>(width * height * 4)};
    CGColorSpaceRef colorSpace = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = CGBitmapContextCreate(
        result.rgba.data(), width, height, 8, width * 4, colorSpace,
        static_cast<CGBitmapInfo>(static_cast<std::uint32_t>(kCGImageAlphaPremultipliedLast) |
                                  static_cast<std::uint32_t>(kCGBitmapByteOrder32Big)));
    CGColorSpaceRelease(colorSpace);
    if (!context) {
        CGImageRelease(image);
        return fail(ErrorCode::resourceExhausted, "Unable to allocate glTF image decode context");
    }
    CGContextTranslateCTM(context, 0.0, static_cast<CGFloat>(height));
    CGContextScaleCTM(context, 1.0, -1.0);
    CGContextDrawImage(context,
                       CGRectMake(0, 0, static_cast<CGFloat>(width), static_cast<CGFloat>(height)),
                       image);
    CGContextRelease(context);
    CGImageRelease(image);
    for (std::size_t pixel = 0; pixel < width * height; ++pixel) {
        const std::uint8_t alpha = result.rgba[pixel * 4 + 3];
        if (alpha == 0)
            continue;
        for (std::size_t channel = 0; channel < 3; ++channel) {
            const std::uint32_t premultiplied = result.rgba[pixel * 4 + channel];
            result.rgba[pixel * 4 + channel] = static_cast<std::uint8_t>(
                std::min(255U, (premultiplied * 255U + alpha / 2U) / alpha));
        }
    }
    return result;
}

Result<std::string> sha256File(const std::filesystem::path& path) {
    package::Sha256 hasher;
    std::ifstream stream(path, std::ios::binary);
    std::array<char, 64 * 1024> buffer{};
    while (stream) {
        stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto count = stream.gcount();
        if (count > 0)
            hasher.update(std::as_bytes(std::span(buffer.data(), static_cast<std::size_t>(count))));
    }
    if (!stream.eof())
        return fail(ErrorCode::io, "Unable to hash file", path);
    return package::Sha256::hex(hasher.finalize());
}

bool environmentFlagEnabled(const char* name) {
    const char* value = std::getenv(name);
    return value && value[0] != '\0' && std::string_view(value) != "0";
}

Result<MetalPtr<MTL::Texture>> uploadTexture(MTL::Device* device, MTL::CommandQueue* queue,
                                             const DecodedImage& image, MTL::PixelFormat format,
                                             const char* label) {
    const std::size_t maximumSide = std::max(image.width, image.height);
    const auto mipLevels = static_cast<NS::UInteger>(std::bit_width(maximumSide));
    auto descriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    descriptor->setTextureType(MTL::TextureType2D);
    descriptor->setPixelFormat(format);
    descriptor->setWidth(image.width);
    descriptor->setHeight(image.height);
    descriptor->setMipmapLevelCount(mipLevels);
    descriptor->setStorageMode(MTL::StorageModeShared);
    descriptor->setUsage(MTL::TextureUsageShaderRead);
    auto texture = adopt(device->newTexture(descriptor.get()));
    if (!texture)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate glTF texture", label);
    texture->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    texture->replaceRegion(MTL::Region::Make2D(0, 0, image.width, image.height), 0,
                           image.rgba.data(), image.width * 4);
    if (mipLevels > 1) {
        MTL::CommandBuffer* commandBuffer = queue->commandBuffer();
        MTL::BlitCommandEncoder* blit =
            commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
        if (!commandBuffer || !blit)
            return fail(ErrorCode::metal, "Unable to create glTF mipmap encoder", label);
        blit->setLabel(NS::String::string("glTF Mipmap Generation", NS::UTF8StringEncoding));
        blit->generateMipmaps(texture.get());
        blit->endEncoding();
        commandBuffer->commit();
    }
    return texture;
}

MTL::SamplerAddressMode samplerAddress(mesh::SamplerAddressMode mode) {
    switch (mode) {
    case mesh::SamplerAddressMode::clampToEdge:
        return MTL::SamplerAddressModeClampToEdge;
    case mesh::SamplerAddressMode::repeat:
        return MTL::SamplerAddressModeRepeat;
    case mesh::SamplerAddressMode::mirroredRepeat:
        return MTL::SamplerAddressModeMirrorRepeat;
    }
    return MTL::SamplerAddressModeRepeat;
}

std::uint32_t tileEntryBudget(std::size_t gaussianCount) {
    constexpr std::uint64_t minimumEntries = 262'144;
    constexpr std::uint64_t maximumEntries = 4'194'304;
    constexpr std::uint64_t expectedTilesPerGaussian = 64;
    const std::uint64_t requested =
        gaussianCount > maximumEntries / expectedTilesPerGaussian
            ? maximumEntries
            : static_cast<std::uint64_t>(gaussianCount) * expectedTilesPerGaussian;
    return static_cast<std::uint32_t>(std::clamp(requested, minimumEntries, maximumEntries));
}
} // namespace

Result<std::unique_ptr<Renderer>> Renderer::create(MTL::Device* device,
                                                   std::filesystem::path shaderLibraryPath) {
    if (!device) {
        return fail(ErrorCode::metal, "No Metal device is available on this Mac");
    }
    auto renderer = std::unique_ptr<Renderer>(new Renderer(device, std::move(shaderLibraryPath)));
    if (!renderer->commandQueue_) {
        return fail(ErrorCode::metal, "Metal failed to create the primary command queue");
    }
    for (std::uint32_t index = 0; index < renderer->frameContexts_.size(); ++index) {
        auto context = FrameContext::create(device, index);
        if (!context) {
            return std::unexpected(context.error());
        }
        renderer->frameContexts_[index] = std::move(*context);
    }
    if (auto pipeline = renderer->buildViewportPipeline(); !pipeline) {
        return std::unexpected(pipeline.error());
    }
    return renderer;
}

Renderer::Renderer(MTL::Device* device, std::filesystem::path shaderLibraryPath)
    : device_(retain(device)), commandQueue_(adopt(device->newCommandQueue())),
      frameSemaphore_(dispatch_semaphore_create(3)), capabilities_(inspect(device)),
      shaderLibraryPath_(std::move(shaderLibraryPath)) {
    if (commandQueue_) {
        commandQueue_->setLabel(NS::String::string("AETHER Primary Queue", NS::UTF8StringEncoding));
    }
    scene::Light sun;
    sun.type = scene::LightType::directional;
    sun.direction = {-0.4F, -1.0F, -0.6F};
    sun.color = {1.0F, 0.95F, 0.85F};
    sun.intensity = 4.0F;
    lights_.push_back(sun);
    Log::instance().write(LogLevel::info, "Initialized Metal device: " + capabilities_.name);
}

Renderer::~Renderer() {
    for (int index = 0; index < 3; ++index) {
        dispatch_semaphore_wait(frameSemaphore_, DISPATCH_TIME_FOREVER);
    }
    for (int index = 0; index < 3; ++index) {
        dispatch_semaphore_signal(frameSemaphore_);
    }
#if !OS_OBJECT_USE_OBJC
    dispatch_release(frameSemaphore_);
#endif
}

void Renderer::draw(MTK::View* view) noexcept {
    ProfileScope profile("Renderer::draw");
    if (!view || !commandQueue_) {
        return;
    }

    NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init();
    const Clock::TimePoint frameTime = Clock::now();
    const double frameSeconds = Clock::secondsBetween(previousFrameTime_, frameTime);
    cameraController_.update(frameSeconds);
    previousFrameTime_ = frameTime;
    if (selectedAnimation_ && meshAnimationAsset_) {
        if (animationPlaying_)
            animationSeconds_ += static_cast<float>(frameSeconds);
        auto localTransforms = mesh::sampleAnimation(*meshAnimationAsset_, *selectedAnimation_,
                                                     animationSeconds_, animationLoop_);
        auto worldTransforms =
            localTransforms
                ? mesh::resolveWorldTransforms(*meshAnimationAsset_, *localTransforms)
                : Result<std::vector<simd_float4x4>>(std::unexpected(localTransforms.error()));
        if (!worldTransforms) {
            Log::instance().write(LogLevel::error, worldTransforms.error().describe());
            selectedAnimation_.reset();
        } else {
            meshWorldTransforms_ = *worldTransforms;
            for (auto& instance : meshInstances_) {
                if (instance.nodeIndex >= worldTransforms->size())
                    continue;
                instance.worldTransform = instance.transformOverride
                                              ? instance.transformOverride->matrix()
                                              : (*worldTransforms)[instance.nodeIndex];
                const auto localCenter = meshPrimitives_[instance.primitiveIndex].localBoundsCenter;
                const auto transformed =
                    simd_mul(instance.worldTransform,
                             simd_float4{localCenter.x, localCenter.y, localCenter.z, 1.0F});
                instance.worldBoundsCenter = {transformed.x, transformed.y, transformed.z};
                instance.mirrored = simd_determinant(instance.worldTransform) < 0.0F;
            }
        }
    }
    if (frameCaptureRequested_.load(std::memory_order_relaxed))
        view->setFramebufferOnly(false);
    MTL::RenderPassDescriptor* renderPass = view->currentRenderPassDescriptor();
    CA::MetalDrawable* drawable = view->currentDrawable();
    if (!renderPass || !drawable) {
        pool->release();
        return;
    }

    dispatch_semaphore_wait(frameSemaphore_, DISPATCH_TIME_FOREVER);
    const std::size_t frameSlot = static_cast<std::size_t>(frameNumber_ % frameContexts_.size());
    FrameContext& frame = *frameContexts_[frameSlot];
    frame.beginFrame();
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    if (!commandBuffer) {
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }

    commandBuffer->setLabel(NS::String::string("AETHER Frame", NS::UTF8StringEncoding));
    MTL::Texture* drawableTexture = drawable->texture();
    if (!drawableTexture || drawableTexture->width() > std::numeric_limits<std::uint32_t>::max() ||
        drawableTexture->height() > std::numeric_limits<std::uint32_t>::max()) {
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    const auto targetWidth = static_cast<std::uint32_t>(drawableTexture->width());
    const auto targetHeight = static_cast<std::uint32_t>(drawableTexture->height());
    if (auto targets = ensureSceneTargets(targetWidth, targetHeight); !targets) {
        Log::instance().write(LogLevel::error, targets.error().describe());
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    if (auto targets = ensureGaussianTargets(targetWidth, targetHeight); !targets) {
        Log::instance().write(LogLevel::error, targets.error().describe());
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    const std::uint64_t jitterIndex = frameNumber_ % 8U + 1U;
    const simd_float2 jitterPixels{halton(jitterIndex, 2U) - 0.5F, halton(jitterIndex, 3U) - 0.5F};
    std::optional<world_gaussian::GaussianImageRevisionCertificate>
        frameGaussianRevisionCertificate;
    bool forceTemporalFullHistoryInvalidation = false;
    bool presentGaussians = false;
    if (gaussianPipeline_) {
        {
            const auto width = targetWidth;
            const auto height = targetHeight;
            auto targets = ensureGaussianTargets(width, height);
            scene::Camera camera;
            camera.verticalFieldOfViewRadians = cameraVerticalFieldOfViewRadians_;
            const scene::Transform cameraTransform = cameraController_.transform();
            auto viewMatrix = camera.viewMatrix(cameraTransform);
            if (targets && viewMatrix && height > 0) {
                simd_float4x4 positiveZView = *viewMatrix;
                for (simd_float4& column : positiveZView.columns)
                    column.z = -column.z;
                const float focal = static_cast<float>(height) /
                                    (2.0F * std::tan(camera.verticalFieldOfViewRadians * 0.5F));
                AetherGaussianCamera gaussianCamera{};
                gaussianCamera.worldToCamera = positiveZView;
                gaussianCamera.focalCenter = {focal, focal,
                                              static_cast<float>(width) * 0.5F + jitterPixels.x,
                                              static_cast<float>(height) * 0.5F + jitterPixels.y};
                gaussianCamera.depthViewport = {
                    camera.nearPlane, camera.infiniteFarPlane ? 10'000.0F : camera.farPlane,
                    static_cast<float>(width), static_cast<float>(height)};
                const simd_float3 cameraPosition = cameraController_.position();
                gaussianCamera.cameraWorldPosition = {cameraPosition.x, cameraPosition.y,
                                                      cameraPosition.z, 1.0F};
                gaussianCamera.debugOptions = {gaussianDebugMode_, 0U, 0U, 0U};

                auto pendingRevision = gaussianPipeline_->pendingRevisionSnapshot();
                if (pendingRevision) {
                    gaussian::ReferenceCamera referenceCamera;
                    referenceCamera.width = width;
                    referenceCamera.height = height;
                    referenceCamera.focalX = gaussianCamera.focalCenter.x;
                    referenceCamera.focalY = gaussianCamera.focalCenter.y;
                    referenceCamera.centerX = gaussianCamera.focalCenter.z;
                    referenceCamera.centerY = gaussianCamera.focalCenter.w;
                    referenceCamera.nearPlane = gaussianCamera.depthViewport.x;
                    referenceCamera.farPlane = gaussianCamera.depthViewport.y;
                    referenceCamera.cameraWorldPosition = {
                        gaussianCamera.cameraWorldPosition.x,
                        gaussianCamera.cameraWorldPosition.y,
                        gaussianCamera.cameraWorldPosition.z,
                    };
                    for (std::size_t row = 0; row < 4; ++row) {
                        for (std::size_t column = 0; column < 4; ++column) {
                            referenceCamera.worldToCamera[row * 4 + column] =
                                positiveZView.columns[column][row];
                        }
                    }

                    auto certificate = world_gaussian::certifyGaussianImageRevision(
                        pendingRevision->beforeChanged, pendingRevision->afterChanged,
                        referenceCamera, pendingRevision->sceneColorUpperBound);
                    if (certificate) {
                        const auto affected = static_cast<std::uint64_t>(std::count_if(
                            certificate->rgbLInfBounds.begin(), certificate->rgbLInfBounds.end(),
                            [](double bound) { return bound > 0.0; }));
                        lastGaussianRevisionCertificateStatistics_ = {
                            .available = true,
                            .invalidationCoversCertifiedSupport = false,
                            .temporalFullFrameFallback = false,
                            .revisionVersion = pendingRevision->version,
                            .changedGaussians = pendingRevision->sourceIndices.size(),
                            .affectedPixels = affected,
                            .fullFramePixels = static_cast<std::uint64_t>(width) * height,
                            .maximumCurrentRgbBound = certificate->maximumRgbLInfBound,
                            .sceneColorUpperBound = pendingRevision->sceneColorUpperBound,
                            .camera = referenceCamera,
                        };
                        frameGaussianRevisionCertificate = std::move(*certificate);
                    } else {
                        forceTemporalFullHistoryInvalidation = true;
                        lastGaussianRevisionCertificateStatistics_ = {
                            .available = false,
                            .invalidationCoversCertifiedSupport = false,
                            .temporalFullFrameFallback = true,
                            .revisionVersion = pendingRevision->version,
                            .changedGaussians = pendingRevision->sourceIndices.size(),
                            .affectedPixels = 0,
                            .fullFramePixels = static_cast<std::uint64_t>(width) * height,
                            .maximumCurrentRgbBound = 0.0,
                            .sceneColorUpperBound = pendingRevision->sceneColorUpperBound,
                            .camera = referenceCamera,
                        };
                        Log::instance().write(LogLevel::error, certificate.error().describe());
                    }
                } else if (pendingRevision.error().code != ErrorCode::notFound) {
                    forceTemporalFullHistoryInvalidation = true;
                    lastGaussianRevisionCertificateStatistics_ = {
                        .available = false,
                        .invalidationCoversCertifiedSupport = false,
                        .temporalFullFrameFallback = true,
                        .revisionVersion = 0,
                        .changedGaussians = 0,
                        .affectedPixels = 0,
                        .fullFramePixels = static_cast<std::uint64_t>(width) * height,
                        .maximumCurrentRgbBound = 0.0,
                        .sceneColorUpperBound = 0.0,
                        .camera = {},
                    };
                    Log::instance().write(LogLevel::error, pendingRevision.error().describe());
                }

                auto encoded =
                    gaussianPipeline_->encode(commandBuffer, gaussianCamera, gaussianColor_.get(),
                                              gaussianDepth_.get(), gaussianIds_.get(), frameSlot);
                if (encoded) {
                    presentGaussians = true;
                    if (frameGaussianRevisionCertificate)
                        gaussianPipeline_->clearPendingRevisionSnapshot();
                } else {
                    Log::instance().write(LogLevel::error, encoded.error().describe());
                }
            } else if (!targets) {
                Log::instance().write(LogLevel::error, targets.error().describe());
            }
        }
    }
    scene::Camera meshCamera;
    meshCamera.verticalFieldOfViewRadians = cameraVerticalFieldOfViewRadians_;
    const scene::Transform meshCameraTransform = cameraController_.transform();
    const float meshWidth = static_cast<float>(targetWidth);
    const float meshHeight = static_cast<float>(targetHeight);
    const float meshAspect = meshHeight > 0.0F ? meshWidth / meshHeight : 16.0F / 9.0F;
    const auto meshProjection = meshCamera.projectionMatrix(meshAspect);
    const auto meshView = meshCamera.viewMatrix(meshCameraTransform);
    std::optional<simd_float4x4> jitteredMeshProjection;
    if (meshProjection) {
        jitteredMeshProjection = *meshProjection;
        const simd_float2 jitterNdc{2.0F * jitterPixels.x / meshWidth,
                                    -2.0F * jitterPixels.y / meshHeight};
        jitteredMeshProjection->columns[2].x -= jitterNdc.x;
        jitteredMeshProjection->columns[2].y -= jitterNdc.y;
    }
    std::optional<scene::DirectionalShadowCascades> shadowCascades;
    std::optional<std::uint32_t> shadowLightIndex;
    AetherLocalShadowUniforms localShadowUniforms{};
    for (auto& matrix : localShadowUniforms.worldToShadow)
        matrix = matrix_identity_float4x4;
    std::uint32_t localShadowLightCount = 0;
    std::uint32_t localShadowSliceCount = 0;
    if (!meshPrimitives_.empty() && meshProjection && meshView) {
        for (std::size_t lightIndex = 0; lightIndex < lights_.size(); ++lightIndex) {
            const auto& light = lights_[lightIndex];
            if (light.type != scene::LightType::directional)
                continue;
            auto built = scene::buildDirectionalShadowCascades(
                meshCamera, meshCameraTransform, meshAspect, light.direction, shadowConfig_);
            if (built) {
                shadowCascades = std::move(*built);
                shadowLightIndex = static_cast<std::uint32_t>(lightIndex);
            } else
                Log::instance().write(LogLevel::error, built.error().describe());
            break;
        }
        auto allocations = scene::selectLocalShadowLights(lights_);
        if (!allocations) {
            Log::instance().write(LogLevel::error, allocations.error().describe());
        } else
            for (const auto& allocation : *allocations) {
                const auto& light = lights_[allocation.sourceLightIndex];
                if (light.type == scene::LightType::spot) {
                    auto projection = scene::buildSpotShadowProjection(light, localShadowConfig_);
                    if (!projection) {
                        Log::instance().write(LogLevel::error, projection.error().describe());
                        continue;
                    }
                    localShadowUniforms.worldToShadow[allocation.baseSlice] =
                        projection->worldToShadowClip;
                    localShadowUniforms.lightMetadata[localShadowLightCount++] = {
                        static_cast<float>(allocation.sourceLightIndex),
                        static_cast<float>(light.type), static_cast<float>(allocation.baseSlice),
                        1.0F};
                } else {
                    auto projection = scene::buildPointShadowProjection(light, localShadowConfig_);
                    if (!projection) {
                        Log::instance().write(LogLevel::error, projection.error().describe());
                        continue;
                    }
                    for (std::uint32_t face = 0; face < allocation.sliceCount; ++face)
                        localShadowUniforms.worldToShadow[allocation.baseSlice + face] =
                            projection->worldToShadowClip[face];
                    localShadowUniforms.lightMetadata[localShadowLightCount++] = {
                        static_cast<float>(allocation.sourceLightIndex),
                        static_cast<float>(light.type), static_cast<float>(allocation.baseSlice),
                        6.0F};
                }
                localShadowSliceCount = allocation.baseSlice + allocation.sliceCount;
            }
    }
    localShadowUniforms.countBias = {static_cast<float>(localShadowLightCount), 0.001F, 0.01F,
                                     0.0F};
    std::vector<std::optional<BufferSlice>> frameSkinPalettes(meshInstances_.size());
    std::vector<std::optional<BufferSlice>> previousFrameSkinPalettes(meshInstances_.size());
    for (std::size_t instanceIndex = 0; instanceIndex < meshInstances_.size(); ++instanceIndex) {
        const auto& instance = meshInstances_[instanceIndex];
        if (!instance.skinIndex || !meshAnimationAsset_ ||
            *instance.skinIndex >= meshAnimationAsset_->skins.size())
            continue;
        const auto& skin = meshAnimationAsset_->skins[*instance.skinIndex];
        std::vector<AetherJointMatrix> palette;
        palette.reserve(skin.jointNodeIndices.size());
        const auto inverseMesh = simd_inverse(instance.worldTransform);
        for (std::size_t joint = 0; joint < skin.jointNodeIndices.size(); ++joint) {
            const auto nodeIndex = skin.jointNodeIndices[joint];
            if (nodeIndex >= meshWorldTransforms_.size())
                break;
            const auto position = simd_mul(simd_mul(inverseMesh, meshWorldTransforms_[nodeIndex]),
                                           skin.inverseBindMatrices[joint]);
            palette.push_back(AetherJointMatrix{position, simd_transpose(simd_inverse(position))});
        }
        if (palette.size() != skin.jointNodeIndices.size()) {
            Log::instance().write(LogLevel::error, "Skin joint world transform is unavailable");
            continue;
        }
        auto slice = frame.allocateUpload(palette.size() * sizeof(AetherJointMatrix), 256);
        if (!slice) {
            Log::instance().write(LogLevel::error, slice.error().describe());
            continue;
        }
        std::memcpy(slice->cpuAddress, palette.data(), palette.size() * sizeof(AetherJointMatrix));
        frameSkinPalettes[instanceIndex] = *slice;

        std::vector<AetherJointMatrix> previousPalette;
        previousPalette.reserve(skin.jointNodeIndices.size());
        const auto inversePreviousMesh = simd_inverse(instance.previousWorldTransform);
        for (std::size_t joint = 0; joint < skin.jointNodeIndices.size(); ++joint) {
            const auto nodeIndex = skin.jointNodeIndices[joint];
            if (nodeIndex >= previousMeshWorldTransforms_.size())
                break;
            const auto position =
                simd_mul(simd_mul(inversePreviousMesh, previousMeshWorldTransforms_[nodeIndex]),
                         skin.inverseBindMatrices[joint]);
            previousPalette.push_back(
                AetherJointMatrix{position, simd_transpose(simd_inverse(position))});
        }
        if (previousPalette.size() != skin.jointNodeIndices.size()) {
            Log::instance().write(LogLevel::error, "Previous skin joint transform is unavailable");
            continue;
        }
        auto previousSlice =
            frame.allocateUpload(previousPalette.size() * sizeof(AetherJointMatrix), 256);
        if (!previousSlice) {
            Log::instance().write(LogLevel::error, previousSlice.error().describe());
            continue;
        }
        std::memcpy(previousSlice->cpuAddress, previousPalette.data(),
                    previousPalette.size() * sizeof(AetherJointMatrix));
        previousFrameSkinPalettes[instanceIndex] = *previousSlice;
    }
    auto bindDeformation = [&](MTL::RenderCommandEncoder* targetEncoder,
                               std::size_t instanceIndex) -> bool {
        const auto& instance = meshInstances_[instanceIndex];
        const auto& primitive = meshPrimitives_[instance.primitiveIndex];
        AetherSkinDraw skinDraw{};
        AetherJointMatrix identityJoint{matrix_identity_float4x4, matrix_identity_float4x4};
        if (instance.skinIndex) {
            if (!frameSkinPalettes[instanceIndex] || !previousFrameSkinPalettes[instanceIndex])
                return false;
            const auto& slice = *frameSkinPalettes[instanceIndex];
            const auto& previousSlice = *previousFrameSkinPalettes[instanceIndex];
            targetEncoder->setVertexBuffer(slice.buffer, slice.offset, 2);
            targetEncoder->setVertexBuffer(previousSlice.buffer, previousSlice.offset, 7);
            skinDraw.jointCount =
                static_cast<std::uint32_t>(slice.size / sizeof(AetherJointMatrix));
            skinDraw.enabled = 1;
        } else {
            targetEncoder->setVertexBytes(&identityJoint, sizeof(identityJoint), 2);
            targetEncoder->setVertexBytes(&identityJoint, sizeof(identityJoint), 7);
        }
        targetEncoder->setVertexBytes(&skinDraw, sizeof(skinDraw), 3);
        targetEncoder->setVertexBytes(&skinDraw, sizeof(skinDraw), 8);
        AetherMorphDraw morphDraw{};
        AetherMorphDelta zeroMorph{};
        float zeroMorphWeight = 0.0F;
        if (primitive.morphTargetCount > 0) {
            if (instance.morphWeights.size() != primitive.morphTargetCount)
                return false;
            targetEncoder->setVertexBuffer(primitive.morphDeltas.get(), 0, 4);
            targetEncoder->setVertexBytes(instance.morphWeights.data(),
                                          instance.morphWeights.size() * sizeof(float), 5);
            if (instance.previousMorphWeights.size() != primitive.morphTargetCount)
                return false;
            targetEncoder->setVertexBytes(instance.previousMorphWeights.data(),
                                          instance.previousMorphWeights.size() * sizeof(float), 9);
            morphDraw = {primitive.morphTargetCount, primitive.vertexCount, 1U, 0U};
        } else {
            targetEncoder->setVertexBytes(&zeroMorph, sizeof(zeroMorph), 4);
            targetEncoder->setVertexBytes(&zeroMorphWeight, sizeof(zeroMorphWeight), 5);
            targetEncoder->setVertexBytes(&zeroMorphWeight, sizeof(zeroMorphWeight), 9);
        }
        targetEncoder->setVertexBytes(&morphDraw, sizeof(morphDraw), 6);
        targetEncoder->setVertexBuffer(primitive.vertices.get(), 0, 0);
        return true;
    };

    if (shadowCascades && shadowPipeline_ && shadowDepthState_) {
        for (std::size_t cascade = 0; cascade < shadowCascades->worldToShadowClip.size();
             ++cascade) {
            MTL::RenderPassDescriptor* shadowPass =
                MTL::RenderPassDescriptor::renderPassDescriptor();
            shadowPass->depthAttachment()->setTexture(directionalShadowMap_.get());
            shadowPass->depthAttachment()->setSlice(cascade);
            shadowPass->depthAttachment()->setLoadAction(MTL::LoadActionClear);
            shadowPass->depthAttachment()->setStoreAction(MTL::StoreActionStore);
            shadowPass->depthAttachment()->setClearDepth(1.0);
            auto* shadowEncoder = commandBuffer->renderCommandEncoder(shadowPass);
            if (!shadowEncoder)
                continue;
            shadowEncoder->setLabel(
                NS::String::string("Directional Shadow Cascade", NS::UTF8StringEncoding));
            shadowEncoder->setRenderPipelineState(shadowPipeline_.get());
            shadowEncoder->setDepthStencilState(shadowDepthState_.get());
            shadowEncoder->setViewport(
                MTL::Viewport{0, 0, static_cast<double>(shadowConfig_.resolution),
                              static_cast<double>(shadowConfig_.resolution), 0.0, 1.0});
            for (std::size_t instanceIndex = 0; instanceIndex < meshInstances_.size();
                 ++instanceIndex) {
                const auto& instance = meshInstances_[instanceIndex];
                const auto& primitive = meshPrimitives_[instance.primitiveIndex];
                const auto& material = meshMaterials_[primitive.materialIndex];
                if (material.alphaBlend || !bindDeformation(shadowEncoder, instanceIndex))
                    continue;
                AetherFrameUniforms shadowFrame{};
                shadowFrame.viewProjection = shadowCascades->worldToShadowClip[cascade];
                shadowFrame.model = instance.worldTransform;
                shadowEncoder->setVertexBytes(&shadowFrame, sizeof(shadowFrame), 1);
                shadowEncoder->setFrontFacingWinding(
                    instance.mirrored ? MTL::WindingClockwise : MTL::WindingCounterClockwise);
                shadowEncoder->setCullMode(material.doubleSided ? MTL::CullModeNone
                                                                : MTL::CullModeBack);
                shadowEncoder->setFragmentBytes(&material.material, sizeof(material.material), 2);
                shadowEncoder->setFragmentTexture(material.textures[0], 0);
                shadowEncoder->setFragmentSamplerState(material.samplers[0], 0);
                shadowEncoder->drawIndexedPrimitives(MTL::PrimitiveTypeTriangle,
                                                     primitive.indexCount, MTL::IndexTypeUInt32,
                                                     primitive.indices.get(), 0);
            }
            shadowEncoder->endEncoding();
        }
    }
    if (localShadowSliceCount > 0 && localShadowMap_ && shadowPipeline_ && shadowDepthState_) {
        for (std::uint32_t slice = 0; slice < localShadowSliceCount; ++slice) {
            MTL::RenderPassDescriptor* shadowPass =
                MTL::RenderPassDescriptor::renderPassDescriptor();
            shadowPass->depthAttachment()->setTexture(localShadowMap_.get());
            shadowPass->depthAttachment()->setSlice(slice);
            shadowPass->depthAttachment()->setLoadAction(MTL::LoadActionClear);
            shadowPass->depthAttachment()->setStoreAction(MTL::StoreActionStore);
            shadowPass->depthAttachment()->setClearDepth(1.0);
            auto* shadowEncoder = commandBuffer->renderCommandEncoder(shadowPass);
            if (!shadowEncoder)
                continue;
            shadowEncoder->setLabel(
                NS::String::string("Local Shadow Slice", NS::UTF8StringEncoding));
            shadowEncoder->setRenderPipelineState(shadowPipeline_.get());
            shadowEncoder->setDepthStencilState(shadowDepthState_.get());
            shadowEncoder->setViewport(
                MTL::Viewport{0, 0, static_cast<double>(localShadowConfig_.resolution),
                              static_cast<double>(localShadowConfig_.resolution), 0.0, 1.0});
            for (std::size_t instanceIndex = 0; instanceIndex < meshInstances_.size();
                 ++instanceIndex) {
                const auto& instance = meshInstances_[instanceIndex];
                const auto& primitive = meshPrimitives_[instance.primitiveIndex];
                const auto& material = meshMaterials_[primitive.materialIndex];
                if (material.alphaBlend || !bindDeformation(shadowEncoder, instanceIndex))
                    continue;
                AetherFrameUniforms shadowFrame{};
                shadowFrame.viewProjection = localShadowUniforms.worldToShadow[slice];
                shadowFrame.model = instance.worldTransform;
                shadowEncoder->setVertexBytes(&shadowFrame, sizeof(shadowFrame), 1);
                shadowEncoder->setFrontFacingWinding(
                    instance.mirrored ? MTL::WindingClockwise : MTL::WindingCounterClockwise);
                shadowEncoder->setCullMode(material.doubleSided ? MTL::CullModeNone
                                                                : MTL::CullModeBack);
                shadowEncoder->setFragmentBytes(&material.material, sizeof(material.material), 2);
                shadowEncoder->setFragmentTexture(material.textures[0], 0);
                shadowEncoder->setFragmentSamplerState(material.samplers[0], 0);
                shadowEncoder->drawIndexedPrimitives(MTL::PrimitiveTypeTriangle,
                                                     primitive.indexCount, MTL::IndexTypeUInt32,
                                                     primitive.indices.get(), 0);
            }
            shadowEncoder->endEncoding();
        }
    }
    MTL::RenderPassDescriptor* proxyPass = MTL::RenderPassDescriptor::renderPassDescriptor();
    auto* proxyNormalAttachment = proxyPass->colorAttachments()->object(0);
    proxyNormalAttachment->setTexture(proxyNormalConfidence_.get());
    proxyNormalAttachment->setLoadAction(MTL::LoadActionClear);
    proxyNormalAttachment->setStoreAction(MTL::StoreActionStore);
    proxyNormalAttachment->setClearColor(MTL::ClearColor::Make(0.5, 0.5, 1.0, 0.0));
    auto* proxyIdAttachment = proxyPass->colorAttachments()->object(1);
    proxyIdAttachment->setTexture(proxyIds_.get());
    proxyIdAttachment->setLoadAction(MTL::LoadActionClear);
    proxyIdAttachment->setStoreAction(MTL::StoreActionStore);
    proxyIdAttachment->setClearColor(MTL::ClearColor::Make(0.0, 0.0, 0.0, 0.0));
    auto* proxyMotionAttachment = proxyPass->colorAttachments()->object(2);
    proxyMotionAttachment->setTexture(proxyMotion_.get());
    proxyMotionAttachment->setLoadAction(MTL::LoadActionClear);
    proxyMotionAttachment->setStoreAction(MTL::StoreActionStore);
    proxyMotionAttachment->setClearColor(MTL::ClearColor::Make(0.0, 0.0, 0.0, 0.0));
    auto* proxyDepthAttachment = proxyPass->depthAttachment();
    proxyDepthAttachment->setTexture(proxyDepth_.get());
    proxyDepthAttachment->setLoadAction(MTL::LoadActionClear);
    proxyDepthAttachment->setStoreAction(MTL::StoreActionStore);
    proxyDepthAttachment->setClearDepth(0.0);
    MTL::RenderCommandEncoder* proxyEncoder = commandBuffer->renderCommandEncoder(proxyPass);
    if (!proxyEncoder) {
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    proxyEncoder->setLabel(NS::String::string("Proxy G-buffer Pass", NS::UTF8StringEncoding));
    if (proxyVertexCount_ > 0 && proxyIndexCount_ > 0 && proxyVertices_ && proxyIndices_ &&
        proxyPipeline_ && reverseZDepthState_ && jitteredMeshProjection && meshView) {
        const simd_float4x4 currentViewProjection = simd_mul(*jitteredMeshProjection, *meshView);
        AetherProxyUniforms proxyUniforms{};
        proxyUniforms.viewProjection = currentViewProjection;
        proxyUniforms.previousViewProjection =
            temporalHistoryValid_ ? previousViewProjection_ : currentViewProjection;
        proxyUniforms.options = {temporalHistoryValid_ ? 1.0F : 0.0F, 0.0F, 0.0F, 0.0F};
        proxyEncoder->setRenderPipelineState(proxyPipeline_.get());
        proxyEncoder->setDepthStencilState(reverseZDepthState_.get());
        proxyEncoder->setCullMode(MTL::CullModeNone);
        proxyEncoder->setVertexBuffer(proxyVertices_.get(), 0, 0);
        proxyEncoder->setVertexBytes(&proxyUniforms, sizeof(proxyUniforms), 1);
        proxyEncoder->setFragmentBytes(&proxyUniforms, sizeof(proxyUniforms), 1);
        proxyEncoder->drawIndexedPrimitives(MTL::PrimitiveTypeTriangle, proxyIndexCount_,
                                            MTL::IndexTypeUInt32, proxyIndices_.get(), 0);
    }
    proxyEncoder->endEncoding();

    MTL::RenderPassDescriptor* scenePass = MTL::RenderPassDescriptor::renderPassDescriptor();
    auto* sceneColorAttachment = scenePass->colorAttachments()->object(0);
    sceneColorAttachment->setTexture(sceneHdrColor_.get());
    sceneColorAttachment->setLoadAction(MTL::LoadActionClear);
    sceneColorAttachment->setStoreAction(MTL::StoreActionStore);
    sceneColorAttachment->setClearColor(MTL::ClearColor::Make(0.0, 0.0, 0.0, 1.0));
    auto* sceneIdAttachment = scenePass->colorAttachments()->object(1);
    sceneIdAttachment->setTexture(sceneIds_.get());
    sceneIdAttachment->setLoadAction(MTL::LoadActionClear);
    sceneIdAttachment->setStoreAction(MTL::StoreActionStore);
    sceneIdAttachment->setClearColor(MTL::ClearColor::Make(0.0, 0.0, 0.0, 0.0));
    auto* sceneMotionAttachment = scenePass->colorAttachments()->object(2);
    sceneMotionAttachment->setTexture(sceneMotion_.get());
    sceneMotionAttachment->setLoadAction(MTL::LoadActionClear);
    sceneMotionAttachment->setStoreAction(MTL::StoreActionStore);
    sceneMotionAttachment->setClearColor(MTL::ClearColor::Make(0.0, 0.0, 0.0, 0.0));
    auto* sceneDepthAttachment = scenePass->depthAttachment();
    sceneDepthAttachment->setTexture(sceneDepth_.get());
    sceneDepthAttachment->setLoadAction(MTL::LoadActionClear);
    sceneDepthAttachment->setStoreAction(MTL::StoreActionStore);
    sceneDepthAttachment->setClearDepth(0.0);
    MTL::RenderCommandEncoder* encoder = commandBuffer->renderCommandEncoder(scenePass);
    if (!encoder) {
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    encoder->setLabel(NS::String::string("Scene HDR Pass", NS::UTF8StringEncoding));
    encoder->setRenderPipelineState(sceneBackgroundPipeline_.get());
    encoder->setDepthStencilState(gaussianCompositionDepthState_.get());
    AetherGaussianCompositionUniforms gaussianComposition{};
    if (jitteredMeshProjection && meshView) {
        const simd_float4x4 currentViewProjection = simd_mul(*jitteredMeshProjection, *meshView);
        gaussianComposition.inverseCurrentViewProjection = simd_inverse(currentViewProjection);
        gaussianComposition.previousViewProjection =
            temporalHistoryValid_ ? previousViewProjection_ : currentViewProjection;
    } else {
        gaussianComposition.inverseCurrentViewProjection = matrix_identity_float4x4;
        gaussianComposition.previousViewProjection = matrix_identity_float4x4;
    }
    gaussianComposition.depthHistoryOpacity = {meshCamera.nearPlane, presentGaussians ? 1.0F : 0.0F,
                                               temporalHistoryValid_ ? 1.0F : 0.0F, 1.0F / 255.0F};
    gaussianComposition.proxyParameters = {proxyIndexCount_ > 0 ? 1.0F : 0.0F, 0.01F, 0.015F, 4.0F};
    encoder->setFragmentBytes(&gaussianComposition, sizeof(gaussianComposition), 0);
    encoder->setFragmentTexture(gaussianColor_.get(), 0);
    encoder->setFragmentTexture(gaussianDepth_.get(), 1);
    encoder->setFragmentTexture(gaussianIds_.get(), 2);
    encoder->setFragmentTexture(proxyNormalConfidence_.get(), 3);
    encoder->setFragmentTexture(proxyDepth_.get(), 4);
    encoder->setFragmentTexture(proxyIds_.get(), 5);
    encoder->setFragmentTexture(proxyMotion_.get(), 6);
    encoder->drawPrimitives(MTL::PrimitiveTypeTriangle, NS::UInteger(0), NS::UInteger(3));

    if (!meshPrimitives_.empty() && pbrPipeline_ && reverseZDepthState_) {
        const auto& camera = meshCamera;
        const float width = meshWidth;
        const float height = meshHeight;
        const auto& projection = meshProjection;
        const auto& viewMatrix = meshView;
        if (projection && jitteredMeshProjection && viewMatrix) {
            AetherFrameUniforms uniforms{};
            uniforms.viewProjection = simd_mul(*jitteredMeshProjection, *viewMatrix);
            uniforms.previousViewProjection =
                temporalHistoryValid_ ? previousViewProjection_ : uniforms.viewProjection;
            uniforms.view = *viewMatrix;
            uniforms.model = matrix_identity_float4x4;
            const simd_float3 cameraPosition = cameraController_.position();
            uniforms.cameraPosition = {cameraPosition.x, cameraPosition.y, cameraPosition.z, 1.0F};
            uniforms.lightDirectionIntensity = {-0.4F, -1.0F, -0.6F, 4.0F};
            uniforms.lightColorExposure = {1.0F, 0.95F, 0.85F, 0.0F};
            {
                scene::ClusterGridConfig clusterConfig;
                clusterConfig.nearDepth = camera.nearPlane;
                clusterConfig.farDepth = camera.infiniteFarPlane ? 10'000.0F : camera.farPlane;
                auto clustered = scene::buildClusteredLightLists(lights_, *viewMatrix, *projection,
                                                                 clusterConfig);
                std::vector<AetherGpuLight> gpuLights;
                if (clustered) {
                    gpuLights.reserve(lights_.size());
                    for (const auto& light : lights_) {
                        const auto direction = light.type == scene::LightType::point
                                                   ? simd_float3{0.0F, -1.0F, 0.0F}
                                                   : simd_normalize(light.direction);
                        gpuLights.push_back(AetherGpuLight{
                            {light.position.x, light.position.y, light.position.z, light.range},
                            {direction.x, direction.y, direction.z,
                             static_cast<float>(static_cast<std::uint32_t>(light.type))},
                            {light.color.x, light.color.y, light.color.z, light.intensity},
                            {std::cos(light.innerConeRadians), std::cos(light.outerConeRadians),
                             0.0F, 0.0F}});
                    }
                }
                std::vector<AetherLightCluster> gpuClusters;
                if (clustered) {
                    gpuClusters.reserve(clustered->clusters.size());
                    for (const auto& cluster : clustered->clusters)
                        gpuClusters.push_back({cluster.offset, cluster.count});
                }
                auto lightSlice =
                    clustered ? frame.allocateUpload(gpuLights.size() * sizeof(AetherGpuLight))
                              : Result<BufferSlice>(std::unexpected(clustered.error()));
                auto clusterSlice =
                    clustered
                        ? frame.allocateUpload(gpuClusters.size() * sizeof(AetherLightCluster))
                        : Result<BufferSlice>(std::unexpected(clustered.error()));
                auto indexSlice = clustered
                                      ? frame.allocateUpload(clustered->lightIndices.size() *
                                                             sizeof(std::uint32_t))
                                      : Result<BufferSlice>(std::unexpected(clustered.error()));
                if (!clustered || !lightSlice || !clusterSlice || !indexSlice) {
                    const auto message = !clustered      ? clustered.error().describe()
                                         : !lightSlice   ? lightSlice.error().describe()
                                         : !clusterSlice ? clusterSlice.error().describe()
                                                         : indexSlice.error().describe();
                    Log::instance().write(LogLevel::error, message);
                    encoder->endEncoding();
                    dispatch_semaphore_signal(frameSemaphore_);
                    pool->release();
                    return;
                }
                std::memcpy(lightSlice->cpuAddress, gpuLights.data(),
                            gpuLights.size() * sizeof(AetherGpuLight));
                std::memcpy(clusterSlice->cpuAddress, gpuClusters.data(),
                            gpuClusters.size() * sizeof(AetherLightCluster));
                std::memcpy(indexSlice->cpuAddress, clustered->lightIndices.data(),
                            clustered->lightIndices.size() * sizeof(std::uint32_t));
                encoder->setFragmentBuffer(lightSlice->buffer, lightSlice->offset, 3);
                encoder->setFragmentBuffer(clusterSlice->buffer, clusterSlice->offset, 4);
                encoder->setFragmentBuffer(indexSlice->buffer, indexSlice->offset, 5);
                AetherClusterUniforms clusterUniforms{};
                clusterUniforms.dimensionsLightCount = {
                    clusterConfig.columns, clusterConfig.rows, clusterConfig.depthSlices,
                    static_cast<std::uint32_t>(gpuLights.size())};
                clusterUniforms.viewportDepth = {width, height, clusterConfig.nearDepth,
                                                 clusterConfig.farDepth};
                encoder->setFragmentBytes(&clusterUniforms, sizeof(clusterUniforms), 6);
                AetherIblUniforms iblUniforms{};
                iblUniforms.specularMaximumMip = iblMaximumMip_;
                iblUniforms.intensity = iblIntensity_;
                iblUniforms.enabled = irradianceTexture_ && specularEnvironmentTexture_ &&
                                              brdfLutTexture_ && environmentSampler_
                                          ? 1U
                                          : 0U;
                encoder->setFragmentBytes(&iblUniforms, sizeof(iblUniforms), 7);
                encoder->setFragmentTexture(irradianceTexture_.get(), 5);
                encoder->setFragmentTexture(specularEnvironmentTexture_.get(), 6);
                encoder->setFragmentTexture(brdfLutTexture_.get(), 7);
                encoder->setFragmentSamplerState(environmentSampler_.get(), 5);
                AetherShadowUniforms shadowUniforms{};
                for (auto& matrix : shadowUniforms.worldToShadow)
                    matrix = matrix_identity_float4x4;
                shadowUniforms.splitDepths = {10'000.0F, 10'000.0F, 10'000.0F, 10'000.0F};
                std::uint32_t activeCascades = 1;
                if (shadowCascades) {
                    activeCascades = static_cast<std::uint32_t>(shadowCascades->splitDepths.size());
                    for (std::size_t index = 0; index < shadowCascades->worldToShadowClip.size();
                         ++index) {
                        shadowUniforms.worldToShadow[index] =
                            shadowCascades->worldToShadowClip[index];
                        shadowUniforms.splitDepths[index] = shadowCascades->splitDepths[index];
                    }
                }
                shadowUniforms.biasNormalCascadeCount = {
                    0.001F, 0.01F, static_cast<float>(activeCascades),
                    static_cast<float>(shadowLightIndex.value_or(0))};
                shadowUniforms.transitionParameters = {0.1F, 0.0F, 0.0F, 0.0F};
                encoder->setFragmentBytes(&shadowUniforms, sizeof(shadowUniforms), 8);
                encoder->setFragmentTexture(directionalShadowMap_.get(), 8);
                encoder->setFragmentSamplerState(shadowComparisonSampler_.get(), 6);
                encoder->setFragmentBytes(&localShadowUniforms, sizeof(localShadowUniforms), 9);
                encoder->setFragmentTexture(localShadowMap_.get(), 9);
                encoder->setFrontFacingWinding(MTL::WindingCounterClockwise);
                auto renderMaterialClass = [&](bool alphaBlend) {
                    encoder->setRenderPipelineState(alphaBlend ? pbrBlendPipeline_.get()
                                                               : pbrPipeline_.get());
                    encoder->setDepthStencilState(alphaBlend ? reverseZReadOnlyDepthState_.get()
                                                             : reverseZDepthState_.get());
                    std::vector<std::size_t> drawOrder;
                    drawOrder.reserve(meshInstances_.size());
                    for (std::size_t index = 0; index < meshInstances_.size(); ++index) {
                        const auto& instance = meshInstances_[index];
                        const auto& primitive = meshPrimitives_.at(instance.primitiveIndex);
                        const auto& material = meshMaterials_.at(primitive.materialIndex);
                        if (material.alphaBlend == alphaBlend)
                            drawOrder.push_back(index);
                    }
                    if (alphaBlend) {
                        std::vector<simd_float3> centers;
                        centers.reserve(meshInstances_.size());
                        for (const auto& instance : meshInstances_)
                            centers.push_back(instance.worldBoundsCenter);
                        drawOrder = mesh::stableBackToFront(drawOrder, centers, cameraPosition);
                    }
                    for (const auto instanceIndex : drawOrder) {
                        const auto& instance = meshInstances_[instanceIndex];
                        const auto& primitive = meshPrimitives_.at(instance.primitiveIndex);
                        const auto& material = meshMaterials_.at(primitive.materialIndex);
                        uniforms.model = instance.worldTransform;
                        uniforms.previousModel = instance.previousWorldTransform;
                        uniforms.normalTransform =
                            simd_transpose(simd_inverse(instance.worldTransform));
                        uniforms.drawIds = {AETHER_MESH_ENTITY_ID_TAG |
                                                static_cast<std::uint32_t>(instanceIndex + 1U),
                                            0U, 0U, 0U};
                        encoder->setVertexBytes(&uniforms, sizeof(uniforms), 1);
                        encoder->setFragmentBytes(&uniforms, sizeof(uniforms), 1);
                        if (!bindDeformation(encoder, instanceIndex))
                            continue;
                        encoder->setFrontFacingWinding(instance.mirrored
                                                           ? MTL::WindingClockwise
                                                           : MTL::WindingCounterClockwise);
                        encoder->setCullMode(material.doubleSided ? MTL::CullModeNone
                                                                  : MTL::CullModeBack);
                        encoder->setFragmentBytes(&material.material, sizeof(material.material), 2);
                        for (std::size_t texture = 0; texture < material.textures.size();
                             ++texture) {
                            encoder->setFragmentTexture(material.textures[texture], texture);
                            encoder->setFragmentSamplerState(material.samplers[texture], texture);
                        }
                        encoder->drawIndexedPrimitives(MTL::PrimitiveTypeTriangle,
                                                       primitive.indexCount, MTL::IndexTypeUInt32,
                                                       primitive.indices.get(), 0);
                    }
                };
                renderMaterialClass(false);
                renderMaterialClass(true);
            }
        }
    }
    if (selectedMeshEntity_ > 0 && selectedMeshEntity_ <= meshInstances_.size() && gizmoPipeline_ &&
        jitteredMeshProjection && meshView) {
        const auto origin = meshInstances_[selectedMeshEntity_ - 1U].worldTransform.columns[3].xyz;
        const float distance = simd_length(cameraController_.position() - origin);
        AetherGizmoUniforms gizmo{};
        gizmo.viewProjection = simd_mul(*jitteredMeshProjection, *meshView);
        gizmo.originScale = {origin.x, origin.y, origin.z,
                             std::clamp(distance * 0.15F, 0.1F, 2.0F)};
        gizmo.viewport = {meshWidth, meshHeight, 1.0F / meshWidth, 1.0F / meshHeight};
        gizmo.options = {gizmoMode_, 0U, 0U, 0U};
        encoder->setRenderPipelineState(gizmoPipeline_.get());
        encoder->setDepthStencilState(reverseZReadOnlyDepthState_.get());
        encoder->setCullMode(MTL::CullModeNone);
        encoder->setVertexBytes(&gizmo, sizeof(gizmo), 0);
        const NS::UInteger vertexCount = gizmoMode_ == 1U ? NS::UInteger(1'152) : NS::UInteger(18);
        encoder->drawPrimitives(MTL::PrimitiveTypeTriangle, NS::UInteger(0), vertexCount);
    }
    encoder->endEncoding();

    MTL::Texture* presentationSource = sceneHdrColor_.get();
    if (temporalPipeline_ && temporalSampler_ && jitteredMeshProjection && meshView) {
        const std::size_t outputIndex = static_cast<std::size_t>(frameNumber_ % 2U);
        const std::size_t inputIndex = 1U - outputIndex;
        const simd_float4x4 currentViewProjection = simd_mul(*jitteredMeshProjection, *meshView);
        float maximumMatrixDelta = 0.0F;
        for (std::size_t column = 0; column < 4; ++column)
            for (std::size_t row = 0; row < 4; ++row)
                maximumMatrixDelta = std::max(
                    maximumMatrixDelta, std::abs(currentViewProjection.columns[column][row] -
                                                 previousViewProjection_.columns[column][row]));
        const bool baseHistoryUsable = temporalHistoryValid_ && maximumMatrixDelta < 0.5F;
        bool historyUsable = baseHistoryUsable;
        bool regionalInvalidation = false;
        bool haveTemporalInvalidationPlan = false;
        simd_float4 invalidationRect{};
        if (pendingTemporalInvalidationBounds_) {
            auto plan = scene::planTemporalInvalidation(
                *pendingTemporalInvalidationBounds_, currentViewProjection,
                static_cast<std::uint32_t>(sceneTargetWidth_),
                static_cast<std::uint32_t>(sceneTargetHeight_), 8);
            if (!plan) {
                haveTemporalInvalidationPlan = true;
                historyUsable = false;
                lastTemporalInvalidationPlan_ = {
                    .fullFrame = true,
                    .empty = false,
                    .normalizedRect = {0.0F, 0.0F, 1.0F, 1.0F},
                    .invalidatedPixels =
                        static_cast<std::uint64_t>(sceneTargetWidth_) * sceneTargetHeight_,
                    .fullFramePixels =
                        static_cast<std::uint64_t>(sceneTargetWidth_) * sceneTargetHeight_,
                };
            } else {
                haveTemporalInvalidationPlan = true;
                lastTemporalInvalidationPlan_ = *plan;
                if (plan->fullFrame) {
                    historyUsable = false;
                } else if (!plan->empty && historyUsable) {
                    regionalInvalidation = true;
                    invalidationRect = plan->normalizedRect;
                }
            }
        }
        if (frameGaussianRevisionCertificate) {
            bool supportCovered = false;
            if (haveTemporalInvalidationPlan) {
                if (lastTemporalInvalidationPlan_.fullFrame) {
                    supportCovered = true;
                } else if (lastTemporalInvalidationPlan_.empty) {
                    supportCovered = lastGaussianRevisionCertificateStatistics_.affectedPixels == 0;
                } else {
                    supportCovered = true;
                    const simd_float4 rect = lastTemporalInvalidationPlan_.normalizedRect;
                    const std::size_t width = frameGaussianRevisionCertificate->width;
                    const std::size_t height = frameGaussianRevisionCertificate->height;
                    for (std::size_t y = 0; y < height && supportCovered; ++y) {
                        for (std::size_t x = 0; x < width; ++x) {
                            const std::size_t pixel = y * width + x;
                            if (frameGaussianRevisionCertificate->rgbLInfBounds[pixel] <= 0.0)
                                continue;
                            const float u =
                                (static_cast<float>(x) + 0.5F) / static_cast<float>(width);
                            const float v =
                                (static_cast<float>(y) + 0.5F) / static_cast<float>(height);
                            if (u < rect.x || u > rect.z || v < rect.y || v > rect.w) {
                                supportCovered = false;
                                break;
                            }
                        }
                    }
                }
            }

            lastGaussianRevisionCertificateStatistics_.invalidationCoversCertifiedSupport =
                supportCovered;

            const bool temporalValidationStable =
                baseHistoryUsable && supportCovered && !forceTemporalFullHistoryInvalidation;
            const double staleHistoryBound = frameGaussianRevisionCertificate->maximumRgbLInfBound;
            const double historyWeight = temporalValidationStable ? 0.9 : 1.0;
            const double fullHistoryWork =
                static_cast<double>(static_cast<std::uint64_t>(sceneTargetWidth_) *
                                    sceneTargetHeight_);
            const double candidateHistoryWork =
                temporalValidationStable && haveTemporalInvalidationPlan
                    ? static_cast<double>(lastTemporalInvalidationPlan_.invalidatedPixels)
                    : fullHistoryWork;

            auto outputGraph = revision::RevisionGraph::build(
                {
                    {"gaussian-current-frame-repaired", 0.0, 0.0},
                    {"temporal-history-repair", candidateHistoryWork, 0.0},
                },
                {},
                fullHistoryWork);
            bool temporalRepairSelected = true;
            if (outputGraph) {
                std::vector<double> sourceBounds{0.0, staleHistoryBound};
                std::vector<revision::RevisionNodeId> hardClosure{0};
                if (!temporalValidationStable)
                    hardClosure.push_back(1);
                const std::vector<revision::RevisionQoI> qois{
                    {"resolved-rgb-linf", {{1, historyWeight}}, gaussianRevisionRgbTolerance_},
                };
                auto planned = revision::greedyCertifiedRevisionCone(*outputGraph, sourceBounds,
                                                                     hardClosure, qois);
                if (planned) {
                    temporalRepairSelected =
                        std::find(planned->cone.begin(), planned->cone.end(),
                                  revision::RevisionNodeId{1}) != planned->cone.end();
                    lastGaussianOutputConePlannerStatistics_ = {
                        .available = true,
                        .stable = planned->stable,
                        .passes = planned->passes,
                        .temporalValidationStable = temporalValidationStable,
                        .temporalRepairSelected = temporalRepairSelected,
                        .fullRebuild = planned->fullRebuild,
                        .resolvedRgbBound = planned->qois.empty()
                                                ? std::numeric_limits<double>::infinity()
                                                : planned->qois.front().bound,
                        .epsilon = gaussianRevisionRgbTolerance_,
                        .historyWeight = historyWeight,
                        .temporalRepairWork = candidateHistoryWork,
                        .plannerWork = planned->work,
                        .fullWork = planned->fullWork,
                    };
                } else {
                    forceTemporalFullHistoryInvalidation = true;
                    lastGaussianOutputConePlannerStatistics_ = {
                        .available = false,
                        .stable = false,
                        .passes = false,
                        .temporalValidationStable = temporalValidationStable,
                        .temporalRepairSelected = true,
                        .fullRebuild = true,
                        .resolvedRgbBound = std::numeric_limits<double>::infinity(),
                        .epsilon = gaussianRevisionRgbTolerance_,
                        .historyWeight = historyWeight,
                        .temporalRepairWork = candidateHistoryWork,
                        .plannerWork = fullHistoryWork,
                        .fullWork = fullHistoryWork,
                    };
                    Log::instance().write(LogLevel::error, planned.error().describe());
                }
            } else {
                forceTemporalFullHistoryInvalidation = true;
                lastGaussianOutputConePlannerStatistics_ = {
                    .available = false,
                    .stable = false,
                    .passes = false,
                    .temporalValidationStable = temporalValidationStable,
                    .temporalRepairSelected = true,
                    .fullRebuild = true,
                    .resolvedRgbBound = std::numeric_limits<double>::infinity(),
                    .epsilon = gaussianRevisionRgbTolerance_,
                    .historyWeight = historyWeight,
                    .temporalRepairWork = candidateHistoryWork,
                    .plannerWork = fullHistoryWork,
                    .fullWork = fullHistoryWork,
                };
                Log::instance().write(LogLevel::error, outputGraph.error().describe());
            }

            if (!temporalRepairSelected && temporalValidationStable &&
                !forceTemporalFullHistoryInvalidation) {
                // CBRC certifies that retaining stale history remains within the
                // declared output tolerance. Current frame rendering is exact,
                // so only the retained-history residual contributes.
                historyUsable = true;
                regionalInvalidation = false;
                invalidationRect = {};
                const std::uint64_t fullPixels =
                    static_cast<std::uint64_t>(sceneTargetWidth_) * sceneTargetHeight_;
                lastTemporalInvalidationPlan_ = {
                    .fullFrame = false,
                    .empty = true,
                    .normalizedRect = {},
                    .invalidatedPixels = 0,
                    .fullFramePixels = fullPixels,
                };
                lastGaussianRevisionCertificateStatistics_.temporalFullFrameFallback = false;
            } else if (!supportCovered || forceTemporalFullHistoryInvalidation ||
                       !baseHistoryUsable) {
                historyUsable = false;
                regionalInvalidation = false;
                const std::uint64_t fullPixels =
                    static_cast<std::uint64_t>(sceneTargetWidth_) * sceneTargetHeight_;
                lastTemporalInvalidationPlan_ = {
                    .fullFrame = true,
                    .empty = false,
                    .normalizedRect = {0.0F, 0.0F, 1.0F, 1.0F},
                    .invalidatedPixels = fullPixels,
                    .fullFramePixels = fullPixels,
                };
                lastGaussianRevisionCertificateStatistics_.temporalFullFrameFallback = true;
            } else if (lastTemporalInvalidationPlan_.fullFrame) {
                historyUsable = false;
                regionalInvalidation = false;
                lastGaussianRevisionCertificateStatistics_.temporalFullFrameFallback = true;
            } else {
                // Planner selected temporal repair and the existing regional
                // plan covers every pixel in certified Gaussian support.
                historyUsable = true;
                regionalInvalidation = !lastTemporalInvalidationPlan_.empty;
                invalidationRect = lastTemporalInvalidationPlan_.normalizedRect;
                lastGaussianRevisionCertificateStatistics_.temporalFullFrameFallback = false;
            }
        } else if (forceTemporalFullHistoryInvalidation) {
            historyUsable = false;
            regionalInvalidation = false;
            const std::uint64_t fullPixels =
                static_cast<std::uint64_t>(sceneTargetWidth_) * sceneTargetHeight_;
            lastTemporalInvalidationPlan_ = {
                .fullFrame = true,
                .empty = false,
                .normalizedRect = {0.0F, 0.0F, 1.0F, 1.0F},
                .invalidatedPixels = fullPixels,
                .fullFramePixels = fullPixels,
            };
        }

        auto* temporalPass = MTL::RenderPassDescriptor::renderPassDescriptor();
        auto* temporalColor = temporalPass->colorAttachments()->object(0);
        temporalColor->setTexture(temporalColorHistory_[outputIndex].get());
        temporalColor->setLoadAction(MTL::LoadActionDontCare);
        temporalColor->setStoreAction(MTL::StoreActionStore);
        auto* temporalDepth = temporalPass->colorAttachments()->object(1);
        temporalDepth->setTexture(temporalDepthHistory_[outputIndex].get());
        temporalDepth->setLoadAction(MTL::LoadActionDontCare);
        temporalDepth->setStoreAction(MTL::StoreActionStore);
        auto* temporalEncoder = commandBuffer->renderCommandEncoder(temporalPass);
        if (temporalEncoder) {
            temporalEncoder->setLabel(
                NS::String::string("Temporal Resolve Pass", NS::UTF8StringEncoding));
            temporalEncoder->setRenderPipelineState(temporalPipeline_.get());
            AetherTemporalUniforms temporal{};
            temporal.inverseCurrentViewProjection = simd_inverse(currentViewProjection);
            temporal.previousViewProjection = previousViewProjection_;
            temporal.historyParameters = {historyUsable ? 1.0F : 0.0F, 0.9F, 0.002F,
                                          regionalInvalidation ? 1.0F : 0.0F};
            temporal.invalidationRect = invalidationRect;
            temporalEncoder->setFragmentBytes(&temporal, sizeof(temporal), 0);
            temporalEncoder->setFragmentTexture(sceneHdrColor_.get(), 0);
            temporalEncoder->setFragmentTexture(sceneDepth_.get(), 1);
            temporalEncoder->setFragmentTexture(temporalColorHistory_[inputIndex].get(), 2);
            temporalEncoder->setFragmentTexture(temporalDepthHistory_[inputIndex].get(), 3);
            temporalEncoder->setFragmentTexture(sceneMotion_.get(), 4);
            temporalEncoder->setFragmentSamplerState(temporalSampler_.get(), 0);
            temporalEncoder->drawPrimitives(MTL::PrimitiveTypeTriangle, NS::UInteger(0),
                                            NS::UInteger(3));
            temporalEncoder->endEncoding();
            presentationSource = temporalColorHistory_[outputIndex].get();
            previousViewProjection_ = currentViewProjection;
            temporalHistoryValid_ = true;
            pendingTemporalInvalidationBounds_.reset();
        }
    }
    bool bloomReady = false;
    if (bloomPipeline_ && temporalSampler_ && bloomHalf_ && bloomQuarter_) {
        auto encodeBloomLevel = [&](MTL::Texture* source, MTL::Texture* destination,
                                    float threshold, float knee, const char* label) {
            auto* bloomPass = MTL::RenderPassDescriptor::renderPassDescriptor();
            auto* attachment = bloomPass->colorAttachments()->object(0);
            attachment->setTexture(destination);
            attachment->setLoadAction(MTL::LoadActionDontCare);
            attachment->setStoreAction(MTL::StoreActionStore);
            auto* bloomEncoder = commandBuffer->renderCommandEncoder(bloomPass);
            if (!bloomEncoder)
                return false;
            bloomEncoder->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
            bloomEncoder->setRenderPipelineState(bloomPipeline_.get());
            AetherBloomUniforms bloom{{1.0F / static_cast<float>(source->width()),
                                       1.0F / static_cast<float>(source->height())},
                                      threshold,
                                      knee};
            bloomEncoder->setFragmentBytes(&bloom, sizeof(bloom), 0);
            bloomEncoder->setFragmentTexture(source, 0);
            bloomEncoder->setFragmentSamplerState(temporalSampler_.get(), 0);
            bloomEncoder->drawPrimitives(MTL::PrimitiveTypeTriangle, NS::UInteger(0),
                                         NS::UInteger(3));
            bloomEncoder->endEncoding();
            return true;
        };
        bloomReady = encodeBloomLevel(presentationSource, bloomHalf_.get(), 1.0F, 0.5F,
                                      "Bloom Threshold Half") &&
                     encodeBloomLevel(bloomHalf_.get(), bloomQuarter_.get(), 0.0F, 0.0F,
                                      "Bloom Downsample Quarter");
    }

    MTL::RenderCommandEncoder* presentationEncoder =
        commandBuffer->renderCommandEncoder(renderPass);
    if (!presentationEncoder) {
        dispatch_semaphore_signal(frameSemaphore_);
        pool->release();
        return;
    }
    presentationEncoder->setLabel(
        NS::String::string("Presentation Tone Map Pass", NS::UTF8StringEncoding));
    presentationEncoder->setRenderPipelineState(viewportPipeline_.get());
    AetherPresentationUniforms presentation{};
    presentation.exposureStops = exposureStops_;
    presentation.mode = shadowDebugMode_ == 0 ? 2U : 2U + shadowDebugMode_;
    presentation.bloomIntensity = bloomReady ? 0.08F : 0.0F;
    presentation.padding1 = shadowDebugSlice_;
    presentationEncoder->setFragmentBytes(&presentation, sizeof(presentation), 0);
    presentationEncoder->setFragmentTexture(presentationSource, 0);
    presentationEncoder->setFragmentTexture(
        bloomReady ? bloomHalf_.get() : fallbackWhiteTexture_.get(), 1);
    presentationEncoder->setFragmentTexture(
        bloomReady ? bloomQuarter_.get() : fallbackWhiteTexture_.get(), 2);
    presentationEncoder->setFragmentTexture(directionalShadowMap_.get(), 3);
    presentationEncoder->setFragmentTexture(localShadowMap_.get(), 4);
    presentationEncoder->setFragmentSamplerState(temporalSampler_.get(), 0);
    presentationEncoder->drawPrimitives(MTL::PrimitiveTypeTriangle, NS::UInteger(0),
                                        NS::UInteger(3));
    presentationEncoder->endEncoding();

    if (frameCaptureRequested_.exchange(false)) {
        const std::size_t compactRowBytes = static_cast<std::size_t>(targetWidth) * 4U;
        const std::size_t captureRowBytes = (compactRowBytes + 255U) & ~std::size_t{255U};
        const std::size_t captureBytes = captureRowBytes * static_cast<std::size_t>(targetHeight);
        MTL::Buffer* captureBuffer =
            device_->newBuffer(captureBytes, MTL::ResourceStorageModeShared);
        MTL::BlitCommandEncoder* captureEncoder =
            captureBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
        if (captureEncoder) {
            captureBuffer->setLabel(
                NS::String::string("Presented Frame Readback", NS::UTF8StringEncoding));
            captureEncoder->setLabel(
                NS::String::string("Presented Frame Capture", NS::UTF8StringEncoding));
            captureEncoder->copyFromTexture(drawableTexture, 0, 0, MTL::Origin::Make(0, 0, 0),
                                            MTL::Size::Make(targetWidth, targetHeight, 1),
                                            captureBuffer, 0, captureRowBytes, captureBytes);
            captureEncoder->endEncoding();
            commandBuffer->addCompletedHandler([this, captureBuffer, targetWidth, targetHeight,
                                                compactRowBytes,
                                                captureRowBytes](MTL::CommandBuffer* completed) {
                if (completed->status() != MTL::CommandBufferStatusError) {
                    FrameCapture capture;
                    capture.width = targetWidth;
                    capture.height = targetHeight;
                    capture.bgra8.resize(compactRowBytes * targetHeight);
                    const auto* source = static_cast<const std::byte*>(captureBuffer->contents());
                    for (std::uint32_t row = 0; row < targetHeight; ++row)
                        std::memcpy(capture.bgra8.data() + row * compactRowBytes,
                                    source + row * captureRowBytes, compactRowBytes);
                    std::lock_guard lock(frameCaptureMutex_);
                    completedFrameCapture_ = std::move(capture);
                }
                captureBuffer->release();
            });
        } else if (captureBuffer) {
            captureBuffer->release();
        }
    }

    dispatch_semaphore_t semaphore = frameSemaphore_;
    commandBuffer->addCompletedHandler([this, semaphore](MTL::CommandBuffer* completed) {
        const double gpuSeconds = completed->GPUEndTime() - completed->GPUStartTime();
        if (gpuSeconds >= 0.0) {
            lastGpuMilliseconds_.store(gpuSeconds * 1000.0, std::memory_order_relaxed);
        }
        completedFrames_.fetch_add(1, std::memory_order_relaxed);
        dispatch_semaphore_signal(semaphore);
    });
    for (auto& instance : meshInstances_) {
        instance.previousWorldTransform = instance.worldTransform;
        instance.previousMorphWeights = instance.morphWeights;
    }
    previousMeshWorldTransforms_ = meshWorldTransforms_;
    commandBuffer->presentDrawable(drawable);
    commandBuffer->commit();
    ++frameNumber_;
    pool->release();
}

void Renderer::drawableSizeWillChange(CGSize size) noexcept {
    drawableSize_ = size;
}

Result<void> Renderer::loadGltf(const std::filesystem::path& path) {
    return loadGltfAsset(path, false);
}

Result<void> Renderer::attachDynamicGltf(const std::filesystem::path& path) {
    if (!gaussianPipeline_)
        return fail(ErrorCode::invalidArgument,
                    "A dynamic glTF asset requires an active captured Gaussian scene");
    return loadGltfAsset(path, true);
}

void Renderer::detachDynamicGltf() noexcept {
    meshPrimitives_.clear();
    meshInstances_.clear();
    meshTextures_.clear();
    meshMaterials_.clear();
    meshAnimationAsset_.reset();
    meshWorldTransforms_.clear();
    previousMeshWorldTransforms_.clear();
    selectedAnimation_.reset();
    selectedMeshEntity_ = 0;
    temporalHistoryValid_ = false;
}

Result<void> Renderer::loadGltfAsset(const std::filesystem::path& path,
                                     bool preserveCapturedWorld) {
    auto loaded = mesh::GltfLoader::load(path);
    if (!loaded) {
        return std::unexpected(loaded.error());
    }
    std::size_t skinUploadBytes = 0;
    for (const auto& instance : loaded->instances) {
        if (!instance.skinIndex)
            continue;
        const auto jointBytes = loaded->skins.at(*instance.skinIndex).jointNodeIndices.size() *
                                sizeof(AetherJointMatrix);
        if (jointBytes > (frameContexts_[0]->uploadCapacity() - skinUploadBytes) / 2U)
            return fail(ErrorCode::resourceExhausted,
                        "glTF skin palettes exceed the per-frame upload budget");
        skinUploadBytes += jointBytes * 2U;
    }

    std::vector<DecodedImage> decodedImages;
    decodedImages.reserve(loaded->images.size());
    for (const auto& image : loaded->images) {
        auto decoded = decodeImage(image.bytes);
        if (!decoded)
            return std::unexpected(decoded.error());
        decodedImages.push_back(std::move(*decoded));
    }
    std::vector<GpuTexture> uploadedTextures;
    uploadedTextures.reserve(loaded->textures.size());
    for (std::size_t index = 0; index < loaded->textures.size(); ++index) {
        const auto& sourceTexture = loaded->textures[index];
        const auto& image = decodedImages.at(sourceTexture.imageIndex);
        const std::string srgbLabel = "glTF Texture " + std::to_string(index) + " sRGB";
        const std::string linearLabel = "glTF Texture " + std::to_string(index) + " Linear";
        auto srgb = uploadTexture(device_.get(), commandQueue_.get(), image,
                                  MTL::PixelFormatRGBA8Unorm_sRGB, srgbLabel.c_str());
        auto linear = uploadTexture(device_.get(), commandQueue_.get(), image,
                                    MTL::PixelFormatRGBA8Unorm, linearLabel.c_str());
        if (!srgb)
            return std::unexpected(srgb.error());
        if (!linear)
            return std::unexpected(linear.error());
        auto descriptor = adopt(MTL::SamplerDescriptor::alloc()->init());
        descriptor->setMinFilter(sourceTexture.minification == mesh::SamplerFilter::nearest
                                     ? MTL::SamplerMinMagFilterNearest
                                     : MTL::SamplerMinMagFilterLinear);
        descriptor->setMagFilter(sourceTexture.magnification == mesh::SamplerFilter::nearest
                                     ? MTL::SamplerMinMagFilterNearest
                                     : MTL::SamplerMinMagFilterLinear);
        switch (sourceTexture.mipFilter) {
        case mesh::SamplerMipFilter::none:
            descriptor->setMipFilter(MTL::SamplerMipFilterNotMipmapped);
            break;
        case mesh::SamplerMipFilter::nearest:
            descriptor->setMipFilter(MTL::SamplerMipFilterNearest);
            break;
        case mesh::SamplerMipFilter::linear:
            descriptor->setMipFilter(MTL::SamplerMipFilterLinear);
            break;
        }
        descriptor->setSAddressMode(samplerAddress(sourceTexture.addressU));
        descriptor->setTAddressMode(samplerAddress(sourceTexture.addressV));
        auto sampler = adopt(device_->newSamplerState(descriptor.get()));
        if (!sampler)
            return fail(ErrorCode::resourceExhausted, "Unable to allocate glTF sampler");
        uploadedTextures.push_back(
            GpuTexture{std::move(*srgb), std::move(*linear), std::move(sampler)});
    }

    std::vector<GpuMaterial> uploadedMaterials;
    uploadedMaterials.reserve(loaded->materials.size());
    for (const auto& sourceMaterial : loaded->materials) {
        GpuMaterial material;
        material.name = sourceMaterial.name.empty()
                            ? "Material " + std::to_string(uploadedMaterials.size() + 1U)
                            : sourceMaterial.name;
        material.textures.fill(fallbackWhiteTexture_.get());
        material.textures[2] = fallbackNormalTexture_.get();
        material.samplers.fill(fallbackSampler_.get());
        material.material.baseColor = sourceMaterial.baseColor;
        material.material.emissiveMetallic = {sourceMaterial.emissive.x, sourceMaterial.emissive.y,
                                              sourceMaterial.emissive.z, sourceMaterial.metallic};
        material.material.roughnessNormalOcclusionAlpha = {
            sourceMaterial.roughness, sourceMaterial.normalScale, sourceMaterial.occlusionStrength,
            sourceMaterial.alphaCutoff};
        std::uint32_t textureMask = 0;
        auto bindTexture = [&](const std::optional<std::size_t>& binding, std::size_t slot,
                               bool srgb, std::uint32_t flag) {
            if (!binding)
                return;
            const auto& texture = uploadedTextures.at(*binding);
            material.textures[slot] = srgb ? texture.srgb.get() : texture.linear.get();
            material.samplers[slot] = texture.sampler.get();
            textureMask |= flag;
        };
        bindTexture(sourceMaterial.baseColorTexture, 0, true, 1U);
        bindTexture(sourceMaterial.metallicRoughnessTexture, 1, false, 2U);
        bindTexture(sourceMaterial.normalTexture, 2, false, 4U);
        bindTexture(sourceMaterial.occlusionTexture, 3, false, 8U);
        bindTexture(sourceMaterial.emissiveTexture, 4, true, 16U);
        const std::uint32_t alphaMode =
            sourceMaterial.alphaMask ? 1U : (sourceMaterial.alphaBlend ? 2U : 0U);
        material.material.textureFlags = {textureMask, alphaMode, 0U, 0U};
        for (std::size_t index = 0; index < sourceMaterial.uvTransforms.size(); ++index) {
            const auto& transform = sourceMaterial.uvTransforms[index];
            material.material.uvScaleOffset[index] = {transform.scale.x, transform.scale.y,
                                                      transform.offset.x, transform.offset.y};
            material.material.uvRotation[index] = {std::cos(transform.rotation),
                                                   std::sin(transform.rotation), 0.0F, 0.0F};
        }
        material.importedMaterial = material.material;
        material.doubleSided = sourceMaterial.doubleSided;
        material.alphaBlend = sourceMaterial.alphaBlend;
        uploadedMaterials.push_back(std::move(material));
    }

    std::vector<GpuMeshPrimitive> uploaded;
    uploaded.reserve(loaded->primitives.size());
    for (const auto& primitive : loaded->primitives) {
        auto vertices = uploadPrivateBuffer(primitive.vertices.data(),
                                            primitive.vertices.size() * sizeof(mesh::MeshVertex),
                                            "glTF Vertex Buffer");
        auto indices = uploadPrivateBuffer(primitive.indices.data(),
                                           primitive.indices.size() * sizeof(std::uint32_t),
                                           "glTF Index Buffer");
        if (!vertices)
            return std::unexpected(vertices.error());
        if (!indices)
            return std::unexpected(indices.error());
        if (primitive.indices.size() > std::numeric_limits<std::uint32_t>::max()) {
            return fail(ErrorCode::resourceExhausted, "Mesh primitive exceeds Metal index count");
        }
        if (primitive.vertices.size() > std::numeric_limits<std::uint32_t>::max() ||
            primitive.morphTargets.size() > std::numeric_limits<std::uint32_t>::max())
            return fail(ErrorCode::resourceExhausted, "Mesh morph dimensions exceed Metal limits");
        MetalPtr<MTL::Buffer> morphBuffer;
        if (!primitive.morphTargets.empty()) {
            std::vector<AetherMorphDelta> deltas;
            deltas.reserve(primitive.morphTargets.size() * primitive.vertices.size());
            for (const auto& target : primitive.morphTargets)
                for (std::size_t vertex = 0; vertex < primitive.vertices.size(); ++vertex)
                    deltas.push_back(AetherMorphDelta{
                        {target.positionDeltas[vertex].x, target.positionDeltas[vertex].y,
                         target.positionDeltas[vertex].z, 0.0F},
                        {target.normalDeltas[vertex].x, target.normalDeltas[vertex].y,
                         target.normalDeltas[vertex].z, 0.0F},
                        {target.tangentDeltas[vertex].x, target.tangentDeltas[vertex].y,
                         target.tangentDeltas[vertex].z, 0.0F}});
            auto uploadedMorphs = uploadPrivateBuffer(
                deltas.data(), deltas.size() * sizeof(AetherMorphDelta), "glTF Morph Delta Buffer");
            if (!uploadedMorphs)
                return std::unexpected(uploadedMorphs.error());
            morphBuffer = std::move(*uploadedMorphs);
        }
        uploaded.push_back(GpuMeshPrimitive{
            std::move(*vertices), std::move(*indices),
            static_cast<std::uint32_t>(primitive.indices.size()), primitive.materialIndex,
            primitive.localBoundsCenter, std::move(morphBuffer),
            static_cast<std::uint32_t>(primitive.morphTargets.size()),
            static_cast<std::uint32_t>(primitive.vertices.size())});
    }
    std::vector<GpuMeshInstance> instances;
    instances.reserve(loaded->instances.size());
    for (const auto& sourceInstance : loaded->instances) {
        if (sourceInstance.primitiveIndex >= loaded->primitives.size())
            return fail(ErrorCode::corruptData, "glTF instance references invalid primitive");
        const auto localCenter =
            loaded->primitives[sourceInstance.primitiveIndex].localBoundsCenter;
        const auto transformed =
            simd_mul(sourceInstance.worldTransform,
                     simd_float4{localCenter.x, localCenter.y, localCenter.z, 1.0F});
        instances.push_back(GpuMeshInstance{sourceInstance.primitiveIndex,
                                            sourceInstance.worldTransform,
                                            sourceInstance.worldTransform,
                                            {transformed.x, transformed.y, transformed.z},
                                            simd_determinant(sourceInstance.worldTransform) < 0.0F,
                                            sourceInstance.nodeIndex,
                                            sourceInstance.skinIndex,
                                            sourceInstance.morphWeights,
                                            sourceInstance.morphWeights,
                                            std::nullopt});
    }
    mesh::MeshAsset animationAsset;
    animationAsset.nodes = std::move(loaded->nodes);
    animationAsset.animations = std::move(loaded->animations);
    animationAsset.skins = std::move(loaded->skins);
    std::vector<scene::Transform> initialTransforms;
    initialTransforms.reserve(animationAsset.nodes.size());
    for (const auto& node : animationAsset.nodes)
        initialTransforms.push_back(node.localTransform);
    auto initialWorlds = mesh::resolveWorldTransforms(animationAsset, initialTransforms);
    if (!initialWorlds)
        return std::unexpected(initialWorlds.error());
    // Publish the fully validated asset as one transaction. Failed replacement leaves the
    // previous dynamic asset and captured world untouched.
    meshPrimitives_ = std::move(uploaded);
    meshInstances_ = std::move(instances);
    meshTextures_ = std::move(uploadedTextures);
    meshMaterials_ = std::move(uploadedMaterials);
    meshAnimationAsset_ = std::move(animationAsset);
    meshWorldTransforms_ = std::move(*initialWorlds);
    previousMeshWorldTransforms_ = meshWorldTransforms_;
    selectedAnimation_ =
        meshAnimationAsset_->animations.empty() ? std::nullopt : std::optional<std::size_t>{0};
    animationSeconds_ = 0.0F;
    animationPlaying_ = true;
    if (!preserveCapturedWorld) {
        gaussianPipeline_.reset();
        proxyVertices_.reset();
        proxyIndices_.reset();
        proxyVertexCount_ = 0;
        proxyIndexCount_ = 0;
    }
    selectedMeshEntity_ = 0;
    temporalHistoryValid_ = false;
    Log::instance().write(LogLevel::info,
                          std::string(preserveCapturedWorld ? "Attached dynamic glTF with "
                                                            : "Loaded glTF scene with ") +
                              std::to_string(meshPrimitives_.size()) + " primitives and " +
                              std::to_string(meshInstances_.size()) + " instances");
    return {};
}

Result<void> Renderer::selectAnimation(std::size_t clipIndex, bool loop) {
    if (!meshAnimationAsset_ || clipIndex >= meshAnimationAsset_->animations.size())
        return fail(ErrorCode::invalidArgument, "Animation clip index is out of range");
    selectedAnimation_ = clipIndex;
    animationLoop_ = loop;
    animationSeconds_ = 0.0F;
    animationPlaying_ = true;
    temporalHistoryValid_ = false;
    return {};
}

void Renderer::seekAnimation(float seconds) noexcept {
    if (std::isfinite(seconds)) {
        animationSeconds_ = std::max(0.0F, seconds);
        temporalHistoryValid_ = false;
    }
}

Result<void> Renderer::setAnimationPlayback(std::optional<std::size_t> clipIndex, float seconds,
                                            bool playing, bool loop) {
    if (!std::isfinite(seconds) || seconds < 0.0F)
        return fail(ErrorCode::invalidArgument, "Animation playback time is invalid");
    if (clipIndex) {
        if (auto selected = selectAnimation(*clipIndex, loop); !selected)
            return std::unexpected(selected.error());
    } else {
        animationLoop_ = loop;
    }
    seekAnimation(seconds);
    animationPlaying_ = playing;
    return {};
}

std::size_t Renderer::animationClipCount() const noexcept {
    return meshAnimationAsset_ ? meshAnimationAsset_->animations.size() : 0;
}

void Renderer::setExposureStops(float stops) noexcept {
    if (std::isfinite(stops))
        exposureStops_ = std::clamp(stops, -16.0F, 16.0F);
}

Result<void> Renderer::setLights(std::vector<scene::Light> lights) {
    if (lights.empty())
        return fail(ErrorCode::invalidArgument, "Renderer requires at least one light");
    constexpr std::size_t maximumLights = 4096;
    if (lights.size() > maximumLights)
        return fail(ErrorCode::resourceExhausted, "Light count exceeds the editor/GPU budget");
    for (const auto& light : lights)
        if (auto valid = scene::validateLight(light); !valid)
            return std::unexpected(valid.error());
    lights_ = std::move(lights);
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::setLight(std::uint32_t lightId, const scene::Light& light) {
    if (lightId == 0 || lightId > lights_.size())
        return fail(ErrorCode::invalidArgument, "Light ID is out of range");
    if (auto valid = scene::validateLight(light); !valid)
        return std::unexpected(valid.error());
    lights_[lightId - 1U] = light;
    temporalHistoryValid_ = false;
    return {};
}

Result<std::uint32_t> Renderer::addLight(const scene::Light& light) {
    constexpr std::size_t maximumLights = 4096;
    if (lights_.size() >= maximumLights)
        return fail(ErrorCode::resourceExhausted, "Light count exceeds the editor/GPU budget");
    if (auto valid = scene::validateLight(light); !valid)
        return std::unexpected(valid.error());
    lights_.push_back(light);
    temporalHistoryValid_ = false;
    return static_cast<std::uint32_t>(lights_.size());
}

Result<void> Renderer::removeLight(std::uint32_t lightId) {
    if (lightId == 0 || lightId > lights_.size())
        return fail(ErrorCode::invalidArgument, "Light ID is out of range");
    if (lights_.size() == 1)
        return fail(ErrorCode::invalidArgument, "Renderer requires at least one light");
    lights_.erase(lights_.begin() + static_cast<std::ptrdiff_t>(lightId - 1U));
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::setImageBasedLighting(const scene::ImageBasedLightingData& data,
                                             float intensity) {
    if (!std::isfinite(intensity) || intensity < 0.0F || data.irradiance.size == 0 ||
        data.prefilteredSpecular.empty() || data.brdfLutSize == 0)
        return fail(ErrorCode::invalidArgument, "IBL data or intensity is invalid");
    const auto cubeTexelCount = [](std::uint32_t size) {
        return static_cast<std::uint64_t>(size) * size * 6;
    };
    if (cubeTexelCount(data.irradiance.size) != data.irradiance.linearRgb.size() ||
        static_cast<std::uint64_t>(data.brdfLutSize) * data.brdfLutSize != data.brdfLut.size())
        return fail(ErrorCode::invalidArgument, "IBL texture dimensions do not match payloads");
    std::uint32_t expectedSize = data.prefilteredSpecular.front().size;
    if (expectedSize == 0)
        return fail(ErrorCode::invalidArgument, "IBL specular cube size is zero");
    for (const auto& level : data.prefilteredSpecular) {
        if (level.size != expectedSize || cubeTexelCount(level.size) != level.linearRgb.size())
            return fail(ErrorCode::invalidArgument, "IBL specular mip chain is inconsistent");
        expectedSize = std::max(1U, expectedSize / 2U);
    }
    auto cubeDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    cubeDescriptor->setTextureType(MTL::TextureTypeCube);
    cubeDescriptor->setPixelFormat(MTL::PixelFormatRGBA32Float);
    cubeDescriptor->setWidth(data.irradiance.size);
    cubeDescriptor->setHeight(data.irradiance.size);
    cubeDescriptor->setMipmapLevelCount(1);
    cubeDescriptor->setStorageMode(MTL::StorageModeShared);
    cubeDescriptor->setUsage(MTL::TextureUsageShaderRead);
    auto irradiance = adopt(device_->newTexture(cubeDescriptor.get()));
    cubeDescriptor->setWidth(data.prefilteredSpecular.front().size);
    cubeDescriptor->setHeight(data.prefilteredSpecular.front().size);
    cubeDescriptor->setMipmapLevelCount(data.prefilteredSpecular.size());
    auto specular = adopt(device_->newTexture(cubeDescriptor.get()));
    auto lutDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    lutDescriptor->setTextureType(MTL::TextureType2D);
    lutDescriptor->setPixelFormat(MTL::PixelFormatRG32Float);
    lutDescriptor->setWidth(data.brdfLutSize);
    lutDescriptor->setHeight(data.brdfLutSize);
    lutDescriptor->setStorageMode(MTL::StorageModeShared);
    lutDescriptor->setUsage(MTL::TextureUsageShaderRead);
    auto lut = adopt(device_->newTexture(lutDescriptor.get()));
    if (!irradiance || !specular || !lut)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate IBL textures");
    auto uploadCubeLevel = [](MTL::Texture* texture, const scene::CubeMapLevel& level,
                              std::uint32_t mip) {
        std::vector<simd_float4> rgba(level.linearRgb.size());
        for (std::size_t index = 0; index < level.linearRgb.size(); ++index)
            rgba[index] = {level.linearRgb[index].x, level.linearRgb[index].y,
                           level.linearRgb[index].z, 1.0F};
        const std::size_t faceTexels = static_cast<std::size_t>(level.size) * level.size;
        for (std::uint32_t face = 0; face < 6; ++face)
            texture->replaceRegion(MTL::Region::Make2D(0, 0, level.size, level.size), mip, face,
                                   rgba.data() + faceTexels * face,
                                   level.size * sizeof(simd_float4),
                                   faceTexels * sizeof(simd_float4));
    };
    uploadCubeLevel(irradiance.get(), data.irradiance, 0);
    for (std::uint32_t mip = 0; mip < data.prefilteredSpecular.size(); ++mip)
        uploadCubeLevel(specular.get(), data.prefilteredSpecular[mip], mip);
    lut->replaceRegion(MTL::Region::Make2D(0, 0, data.brdfLutSize, data.brdfLutSize), 0,
                       data.brdfLut.data(), data.brdfLutSize * sizeof(simd_float2));
    auto samplerDescriptor = adopt(MTL::SamplerDescriptor::alloc()->init());
    samplerDescriptor->setLabel(
        NS::String::string("IBL Trilinear Sampler", NS::UTF8StringEncoding));
    samplerDescriptor->setMinFilter(MTL::SamplerMinMagFilterLinear);
    samplerDescriptor->setMagFilter(MTL::SamplerMinMagFilterLinear);
    samplerDescriptor->setMipFilter(MTL::SamplerMipFilterLinear);
    samplerDescriptor->setSAddressMode(MTL::SamplerAddressModeClampToEdge);
    samplerDescriptor->setTAddressMode(MTL::SamplerAddressModeClampToEdge);
    auto sampler = adopt(device_->newSamplerState(samplerDescriptor.get()));
    if (!sampler)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate IBL sampler");
    irradiance->setLabel(NS::String::string("IBL Diffuse Irradiance", NS::UTF8StringEncoding));
    specular->setLabel(NS::String::string("IBL Prefiltered Specular", NS::UTF8StringEncoding));
    lut->setLabel(NS::String::string("IBL Split Sum BRDF", NS::UTF8StringEncoding));
    irradianceTexture_ = std::move(irradiance);
    specularEnvironmentTexture_ = std::move(specular);
    brdfLutTexture_ = std::move(lut);
    environmentSampler_ = std::move(sampler);
    iblMaximumMip_ = static_cast<float>(data.prefilteredSpecular.size() - 1);
    iblIntensity_ = intensity;
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::loadPly(const std::filesystem::path& path) {
    auto asset = gaussian::PlyLoader::load(path);
    if (!asset)
        return std::unexpected(asset.error());
    auto pipeline = GaussianPipeline::create(device_.get(), shaderLibrary_.get(),
                                             tileEntryBudget(asset->gaussians.size()));
    if (!pipeline)
        return std::unexpected(pipeline.error());
    if (auto loaded = (*pipeline)->load(*asset); !loaded)
        return std::unexpected(loaded.error());
    meshPrimitives_.clear();
    meshInstances_.clear();
    meshAnimationAsset_.reset();
    meshWorldTransforms_.clear();
    previousMeshWorldTransforms_.clear();
    selectedAnimation_.reset();
    meshTextures_.clear();
    meshMaterials_.clear();
    gaussianPipeline_ = std::move(*pipeline);
    proxyVertices_.reset();
    proxyIndices_.reset();
    proxyVertexCount_ = 0;
    proxyIndexCount_ = 0;
    selectedMeshEntity_ = 0;
    temporalHistoryValid_ = false;
    Log::instance().write(LogLevel::info, "Loaded PLY scene with " +
                                              std::to_string(asset->gaussians.size()) +
                                              " Gaussians");
    return {};
}

Result<void> Renderer::loadAether(const std::filesystem::path& path) {
    auto scenePackage = package::PackageReader::open(path);
    if (!scenePackage)
        return std::unexpected(scenePackage.error());
    auto bytes = scenePackage->readChunk(package::ChunkType::baseGaussians);
    if (!bytes)
        return std::unexpected(bytes.error());
    auto asset = gaussian::GaussianCodec::decode(*bytes);
    if (!asset)
        return std::unexpected(asset.error());
    auto pipeline = GaussianPipeline::create(device_.get(), shaderLibrary_.get(),
                                             tileEntryBudget(asset->gaussians.size()));
    if (!pipeline)
        return std::unexpected(pipeline.error());
    if (auto loaded = (*pipeline)->load(*asset); !loaded)
        return std::unexpected(loaded.error());
    MetalPtr<MTL::Buffer> proxyVertices;
    MetalPtr<MTL::Buffer> proxyIndices;
    std::uint32_t proxyVertexCount = 0;
    std::uint32_t proxyIndexCount = 0;
    const bool hasProxyChunk =
        std::ranges::any_of(scenePackage->info().chunks, [](const package::ChunkInfo& chunk) {
            return chunk.type == package::ChunkType::proxyMesh;
        });
    if (hasProxyChunk) {
        auto proxyBytes = scenePackage->readChunk(package::ChunkType::proxyMesh);
        if (!proxyBytes)
            return std::unexpected(proxyBytes.error());
        auto proxy = hybrid::ProxyMeshCodec::decode(*proxyBytes);
        if (!proxy)
            return std::unexpected(proxy.error());
        if (proxy->vertices.size() > std::numeric_limits<std::uint32_t>::max() ||
            proxy->indices.size() > std::numeric_limits<std::uint32_t>::max())
            return fail(ErrorCode::resourceExhausted, "Proxy mesh exceeds Metal index limits");
        std::vector<AetherProxyGpuVertex> gpuVertices;
        gpuVertices.reserve(proxy->vertices.size());
        for (const auto& vertex : proxy->vertices) {
            gpuVertices.push_back(
                {{vertex.position[0], vertex.position[1], vertex.position[2], vertex.confidence},
                 {vertex.normal[0], vertex.normal[1], vertex.normal[2], 0.0F}});
        }
        auto uploadedVertices = uploadPrivateBuffer(
            gpuVertices.data(), gpuVertices.size() * sizeof(AetherProxyGpuVertex),
            "Proxy Vertex Buffer");
        auto uploadedIndices = uploadPrivateBuffer(proxy->indices.data(),
                                                   proxy->indices.size() * sizeof(std::uint32_t),
                                                   "Proxy Index Buffer");
        if (!uploadedVertices)
            return std::unexpected(uploadedVertices.error());
        if (!uploadedIndices)
            return std::unexpected(uploadedIndices.error());
        proxyVertices = std::move(*uploadedVertices);
        proxyIndices = std::move(*uploadedIndices);
        proxyVertexCount = static_cast<std::uint32_t>(proxy->vertices.size());
        proxyIndexCount = static_cast<std::uint32_t>(proxy->indices.size());
    }
    meshPrimitives_.clear();
    meshInstances_.clear();
    meshAnimationAsset_.reset();
    meshWorldTransforms_.clear();
    previousMeshWorldTransforms_.clear();
    selectedAnimation_.reset();
    meshTextures_.clear();
    meshMaterials_.clear();
    gaussianPipeline_ = std::move(*pipeline);
    proxyVertices_ = std::move(proxyVertices);
    proxyIndices_ = std::move(proxyIndices);
    proxyVertexCount_ = proxyVertexCount;
    proxyIndexCount_ = proxyIndexCount;
    selectedMeshEntity_ = 0;
    temporalHistoryValid_ = false;
    Log::instance().write(LogLevel::info,
                          "Loaded AETHER scene with " + std::to_string(asset->gaussians.size()) +
                              " Gaussians and " + std::to_string(proxyIndexCount_ / 3U) +
                              " proxy triangles");
    return {};
}

Result<std::uint32_t> Renderer::pickGaussian(std::uint32_t x, std::uint32_t y) {
    if (!gaussianIds_)
        return fail(ErrorCode::invalidArgument, "No Gaussian ID target is available");
    if (x >= gaussianTargetWidth_ || y >= gaussianTargetHeight_)
        return fail(ErrorCode::invalidArgument, "Gaussian pick coordinate is outside the viewport");
    constexpr std::size_t readbackBytesPerRow = 256;
    auto readback = adopt(device_->newBuffer(readbackBytesPerRow, MTL::ResourceStorageModeShared));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!readback || !commandBuffer || !blit)
        return fail(ErrorCode::metal, "Unable to allocate Gaussian pick readback");
    readback->setLabel(NS::String::string("Gaussian Pick Readback", NS::UTF8StringEncoding));
    blit->setLabel(NS::String::string("Gaussian ID Pick", NS::UTF8StringEncoding));
    blit->copyFromTexture(gaussianIds_.get(), 0, 0, MTL::Origin::Make(x, y, 0),
                          MTL::Size::Make(1, 1, 1), readback.get(), 0, readbackBytesPerRow,
                          readbackBytesPerRow);
    blit->endEncoding();
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError)
        return fail(ErrorCode::metal, "Gaussian pick command buffer failed");
    std::uint32_t sourceId{};
    std::memcpy(&sourceId, readback->contents(), sizeof(sourceId));
    return sourceId;
}

Result<std::uint32_t> Renderer::pickProxy(std::uint32_t x, std::uint32_t y) {
    if (!proxyIds_)
        return fail(ErrorCode::invalidArgument, "No proxy ID target is available");
    if (x >= sceneTargetWidth_ || y >= sceneTargetHeight_)
        return fail(ErrorCode::invalidArgument, "Proxy pick coordinate is outside the viewport");
    constexpr std::size_t readbackBytesPerRow = 256;
    auto readback = adopt(device_->newBuffer(readbackBytesPerRow, MTL::ResourceStorageModeShared));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!readback || !commandBuffer || !blit)
        return fail(ErrorCode::metal, "Unable to allocate proxy pick readback");
    readback->setLabel(NS::String::string("Proxy Pick Readback", NS::UTF8StringEncoding));
    blit->setLabel(NS::String::string("Proxy ID Pick", NS::UTF8StringEncoding));
    blit->copyFromTexture(proxyIds_.get(), 0, 0, MTL::Origin::Make(x, y, 0),
                          MTL::Size::Make(1, 1, 1), readback.get(), 0, readbackBytesPerRow,
                          readbackBytesPerRow);
    blit->endEncoding();
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError)
        return fail(ErrorCode::metal, "Proxy pick command buffer failed");
    std::uint32_t proxyId{};
    std::memcpy(&proxyId, readback->contents(), sizeof(proxyId));
    return proxyId;
}

Result<std::uint32_t> Renderer::pickMesh(std::uint32_t x, std::uint32_t y) {
    if (!sceneIds_)
        return fail(ErrorCode::invalidArgument, "No mesh entity-ID target is available");
    if (x >= sceneTargetWidth_ || y >= sceneTargetHeight_)
        return fail(ErrorCode::invalidArgument, "Mesh pick coordinate is outside the viewport");
    constexpr std::size_t readbackBytesPerRow = 256;
    auto readback = adopt(device_->newBuffer(readbackBytesPerRow, MTL::ResourceStorageModeShared));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!readback || !commandBuffer || !blit)
        return fail(ErrorCode::metal, "Unable to allocate mesh pick readback");
    readback->setLabel(NS::String::string("Mesh Pick Readback", NS::UTF8StringEncoding));
    blit->setLabel(NS::String::string("Mesh Entity-ID Pick", NS::UTF8StringEncoding));
    blit->copyFromTexture(sceneIds_.get(), 0, 0, MTL::Origin::Make(x, y, 0),
                          MTL::Size::Make(1, 1, 1), readback.get(), 0, readbackBytesPerRow,
                          readbackBytesPerRow);
    blit->endEncoding();
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError)
        return fail(ErrorCode::metal, "Mesh pick command buffer failed");
    std::uint32_t entityId{};
    std::memcpy(&entityId, readback->contents(), sizeof(entityId));
    if ((entityId & AETHER_MESH_ENTITY_ID_TAG) == 0U)
        return 0U;
    entityId &= AETHER_MESH_ENTITY_ID_MASK;
    if (entityId > meshInstances_.size())
        return fail(ErrorCode::corruptData, "Mesh pick target contains an invalid entity ID");
    return entityId;
}

std::vector<std::string> Renderer::meshEntityNames() const {
    std::vector<std::string> names;
    names.reserve(meshInstances_.size());
    for (std::size_t index = 0; index < meshInstances_.size(); ++index) {
        const auto nodeIndex = meshInstances_[index].nodeIndex;
        std::string name;
        if (meshAnimationAsset_ && nodeIndex < meshAnimationAsset_->nodes.size())
            name = meshAnimationAsset_->nodes[nodeIndex].name;
        if (name.empty())
            name = "Entity " + std::to_string(index + 1U);
        names.push_back(std::move(name));
    }
    return names;
}

Result<MeshEntitySnapshot> Renderer::meshEntitySnapshot(std::uint32_t entityId) const {
    if (entityId == 0 || entityId > meshInstances_.size())
        return fail(ErrorCode::invalidArgument, "Mesh entity ID is out of range");
    const auto& instance = meshInstances_[entityId - 1U];
    auto transform = scene::decomposeTransform(instance.worldTransform);
    if (!transform)
        return fail(transform.error().code, "Mesh entity world transform is not editable",
                    transform.error().describe());
    const auto names = meshEntityNames();
    return MeshEntitySnapshot{entityId, names[entityId - 1U], *transform,
                              instance.transformOverride.has_value()};
}

Result<void> Renderer::setMeshEntityTransform(std::uint32_t entityId,
                                              const scene::Transform& transform) {
    if (entityId == 0 || entityId > meshInstances_.size())
        return fail(ErrorCode::invalidArgument, "Mesh entity ID is out of range");
    const float rotationLength = simd_length(transform.rotation.vector);
    if (!scene::isFinite(transform) || !scene::hasNonZeroScale(transform) ||
        !std::isfinite(rotationLength) || rotationLength < 1.0e-6F)
        return fail(ErrorCode::invalidArgument, "Mesh entity transform is invalid");
    scene::Transform normalized = transform;
    normalized.rotation = simd_normalize(normalized.rotation);
    auto& instance = meshInstances_[entityId - 1U];
    instance.transformOverride = normalized;
    instance.worldTransform = normalized.matrix();
    const auto localCenter = meshPrimitives_[instance.primitiveIndex].localBoundsCenter;
    const auto transformed = simd_mul(
        instance.worldTransform, simd_float4{localCenter.x, localCenter.y, localCenter.z, 1.0F});
    instance.worldBoundsCenter = transformed.xyz;
    instance.mirrored = simd_determinant(instance.worldTransform) < 0.0F;
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::clearMeshEntityTransform(std::uint32_t entityId) {
    if (entityId == 0 || entityId > meshInstances_.size())
        return fail(ErrorCode::invalidArgument, "Mesh entity ID is out of range");
    auto& instance = meshInstances_[entityId - 1U];
    instance.transformOverride.reset();
    if (instance.nodeIndex < meshWorldTransforms_.size())
        instance.worldTransform = meshWorldTransforms_[instance.nodeIndex];
    const auto localCenter = meshPrimitives_[instance.primitiveIndex].localBoundsCenter;
    const auto transformed = simd_mul(
        instance.worldTransform, simd_float4{localCenter.x, localCenter.y, localCenter.z, 1.0F});
    instance.worldBoundsCenter = transformed.xyz;
    instance.mirrored = simd_determinant(instance.worldTransform) < 0.0F;
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::setSelectedMeshEntity(std::uint32_t entityId) {
    if (entityId > meshInstances_.size())
        return fail(ErrorCode::invalidArgument, "Selected mesh entity ID is out of range");
    selectedMeshEntity_ = entityId;
    return {};
}

Result<std::uint32_t> Renderer::pickGizmoAxis(std::uint32_t x, std::uint32_t y) {
    if (!sceneIds_ || x >= sceneTargetWidth_ || y >= sceneTargetHeight_)
        return fail(ErrorCode::invalidArgument, "Gizmo pick coordinate is outside the viewport");
    constexpr std::size_t readbackBytesPerRow = 256;
    auto readback = adopt(device_->newBuffer(readbackBytesPerRow, MTL::ResourceStorageModeShared));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!readback || !commandBuffer || !blit)
        return fail(ErrorCode::metal, "Unable to allocate gizmo pick readback");
    blit->setLabel(NS::String::string("Translation Gizmo Pick", NS::UTF8StringEncoding));
    blit->copyFromTexture(sceneIds_.get(), 0, 0, MTL::Origin::Make(x, y, 0),
                          MTL::Size::Make(1, 1, 1), readback.get(), 0, readbackBytesPerRow,
                          readbackBytesPerRow);
    blit->endEncoding();
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError)
        return fail(ErrorCode::metal, "Gizmo pick command buffer failed");
    std::uint32_t encoded{};
    std::memcpy(&encoded, readback->contents(), sizeof(encoded));
    if ((encoded & 0x80000000U) == 0)
        return 0U;
    const std::uint32_t axis = encoded & 0x7fffffffU;
    if (axis < 1U || axis > 3U)
        return fail(ErrorCode::corruptData, "Gizmo target contains an invalid axis ID");
    return axis;
}

Result<simd_float4> Renderer::sampleMotionVector(std::uint32_t x, std::uint32_t y) {
    if (!sceneMotion_ || x >= sceneTargetWidth_ || y >= sceneTargetHeight_)
        return fail(ErrorCode::invalidArgument, "Motion sample coordinate is outside the viewport");
    constexpr std::size_t readbackBytesPerRow = 256;
    auto readback = adopt(device_->newBuffer(readbackBytesPerRow, MTL::ResourceStorageModeShared));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!readback || !commandBuffer || !blit)
        return fail(ErrorCode::metal, "Unable to allocate motion-vector readback");
    blit->setLabel(NS::String::string("Motion Vector Sample", NS::UTF8StringEncoding));
    blit->copyFromTexture(sceneMotion_.get(), 0, 0, MTL::Origin::Make(x, y, 0),
                          MTL::Size::Make(1, 1, 1), readback.get(), 0, readbackBytesPerRow,
                          readbackBytesPerRow);
    blit->endEncoding();
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError)
        return fail(ErrorCode::metal, "Motion-vector sample command buffer failed");
    simd_half4 encoded{};
    std::memcpy(&encoded, readback->contents(), sizeof(encoded));
    return simd_float4{static_cast<float>(encoded.x), static_cast<float>(encoded.y),
                       static_cast<float>(encoded.z), static_cast<float>(encoded.w)};
}

Result<MeshEntitySnapshot> Renderer::translateSelectedMesh(std::uint32_t axis,
                                                           float worldDistance) {
    if (selectedMeshEntity_ == 0 || selectedMeshEntity_ > meshInstances_.size())
        return fail(ErrorCode::invalidArgument, "No mesh entity is selected");
    if (axis < 1U || axis > 3U || !std::isfinite(worldDistance))
        return fail(ErrorCode::invalidArgument, "Translation gizmo delta is invalid");
    auto snapshot = meshEntitySnapshot(selectedMeshEntity_);
    if (!snapshot)
        return std::unexpected(snapshot.error());
    snapshot->worldTransform.translation[axis - 1U] += worldDistance;
    if (auto updated = setMeshEntityTransform(selectedMeshEntity_, snapshot->worldTransform);
        !updated)
        return std::unexpected(updated.error());
    return meshEntitySnapshot(selectedMeshEntity_);
}

Result<MeshEntitySnapshot> Renderer::translateSelectedMeshPixels(std::uint32_t axis,
                                                                 float pixelDistance) {
    if (!std::isfinite(pixelDistance) || sceneTargetHeight_ == 0)
        return fail(ErrorCode::invalidArgument, "Translation gizmo pixel delta is invalid");
    auto snapshot = meshEntitySnapshot(selectedMeshEntity_);
    if (!snapshot)
        return std::unexpected(snapshot.error());
    const float cameraDistance =
        simd_length(cameraController_.position() - snapshot->worldTransform.translation);
    scene::Camera camera;
    camera.verticalFieldOfViewRadians = cameraVerticalFieldOfViewRadians_;
    const float worldPerPixel = 2.0F * cameraDistance *
                                std::tan(camera.verticalFieldOfViewRadians * 0.5F) /
                                static_cast<float>(sceneTargetHeight_);
    return translateSelectedMesh(axis, pixelDistance * worldPerPixel);
}

Result<MeshEntitySnapshot> Renderer::rotateSelectedMeshPixels(std::uint32_t axis,
                                                              float pixelDistance) {
    if (selectedMeshEntity_ == 0 || selectedMeshEntity_ > meshInstances_.size() || axis < 1U ||
        axis > 3U || !std::isfinite(pixelDistance))
        return fail(ErrorCode::invalidArgument, "Rotation gizmo delta is invalid");
    auto snapshot = meshEntitySnapshot(selectedMeshEntity_);
    if (!snapshot)
        return std::unexpected(snapshot.error());
    simd_float3 axisVector{};
    axisVector[axis - 1U] = 1.0F;
    const simd_quatf delta = simd_quaternion(pixelDistance * 0.01F, axisVector);
    snapshot->worldTransform.rotation =
        simd_normalize(simd_mul(snapshot->worldTransform.rotation, delta));
    if (auto updated = setMeshEntityTransform(selectedMeshEntity_, snapshot->worldTransform);
        !updated)
        return std::unexpected(updated.error());
    return meshEntitySnapshot(selectedMeshEntity_);
}

Result<MeshEntitySnapshot> Renderer::scaleSelectedMeshPixels(std::uint32_t axis,
                                                             float pixelDistance) {
    if (selectedMeshEntity_ == 0 || selectedMeshEntity_ > meshInstances_.size() || axis < 1U ||
        axis > 3U || !std::isfinite(pixelDistance))
        return fail(ErrorCode::invalidArgument, "Scale gizmo delta is invalid");
    auto snapshot = meshEntitySnapshot(selectedMeshEntity_);
    if (!snapshot)
        return std::unexpected(snapshot.error());
    const float factor = std::exp(std::clamp(pixelDistance * 0.01F, -4.0F, 4.0F));
    const float component = snapshot->worldTransform.scale[axis - 1U];
    const float sign = component < 0.0F ? -1.0F : 1.0F;
    snapshot->worldTransform.scale[axis - 1U] =
        sign * std::clamp(std::abs(component) * factor, 1.0e-4F, 1.0e4F);
    if (auto updated = setMeshEntityTransform(selectedMeshEntity_, snapshot->worldTransform);
        !updated)
        return std::unexpected(updated.error());
    return meshEntitySnapshot(selectedMeshEntity_);
}

std::vector<MaterialSnapshot> Renderer::materialSnapshots() const {
    std::vector<MaterialSnapshot> result;
    result.reserve(meshMaterials_.size());
    for (std::size_t index = 0; index < meshMaterials_.size(); ++index) {
        const auto& source = meshMaterials_[index];
        result.push_back(MaterialSnapshot{
            static_cast<std::uint32_t>(index + 1U), source.name, source.material.baseColor,
            source.material.emissiveMetallic.xyz, source.material.emissiveMetallic.w,
            source.material.roughnessNormalOcclusionAlpha.x,
            source.material.roughnessNormalOcclusionAlpha.y,
            source.material.roughnessNormalOcclusionAlpha.z,
            source.material.roughnessNormalOcclusionAlpha.w, source.overridden});
    }
    return result;
}

Result<void> Renderer::setMaterialOverride(const MaterialSnapshot& material) {
    if (material.id == 0 || material.id > meshMaterials_.size())
        return fail(ErrorCode::invalidArgument, "Material ID is out of range");
    const auto finite4 = [](simd_float4 value) {
        return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z) &&
               std::isfinite(value.w);
    };
    const auto finite3 = [](simd_float3 value) {
        return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
    };
    if (!finite4(material.baseColor) || !finite3(material.emissive) ||
        !std::isfinite(material.metallic) || !std::isfinite(material.roughness) ||
        !std::isfinite(material.normalScale) || !std::isfinite(material.occlusionStrength) ||
        !std::isfinite(material.alphaCutoff) || simd_reduce_min(material.baseColor) < 0.0F ||
        simd_reduce_max(material.baseColor) > 1.0F || simd_reduce_min(material.emissive) < 0.0F ||
        simd_reduce_max(material.emissive) > 65'504.0F || material.metallic < 0.0F ||
        material.metallic > 1.0F || material.roughness < 0.0F || material.roughness > 1.0F ||
        material.normalScale < 0.0F || material.normalScale > 8.0F ||
        material.occlusionStrength < 0.0F || material.occlusionStrength > 1.0F ||
        material.alphaCutoff < 0.0F || material.alphaCutoff > 1.0F)
        return fail(ErrorCode::invalidArgument, "Material override factors are invalid");
    auto& destination = meshMaterials_[material.id - 1U];
    destination.material.baseColor = material.baseColor;
    destination.material.emissiveMetallic = {material.emissive.x, material.emissive.y,
                                             material.emissive.z, material.metallic};
    destination.material.roughnessNormalOcclusionAlpha = {
        material.roughness, material.normalScale, material.occlusionStrength, material.alphaCutoff};
    destination.overridden = true;
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::clearMaterialOverride(std::uint32_t materialId) {
    if (materialId == 0 || materialId > meshMaterials_.size())
        return fail(ErrorCode::invalidArgument, "Material ID is out of range");
    auto& material = meshMaterials_[materialId - 1U];
    material.material = material.importedMaterial;
    material.overridden = false;
    temporalHistoryValid_ = false;
    return {};
}

Result<void> Renderer::ensureSceneTargets(std::uint32_t width, std::uint32_t height) {
    if (width == 0 || height == 0)
        return fail(ErrorCode::invalidArgument, "Scene render target dimensions are zero");
    if (sceneHdrColor_ && sceneDepth_ && sceneIds_ && sceneMotion_ && proxyNormalConfidence_ &&
        proxyIds_ && proxyMotion_ && proxyDepth_ && bloomHalf_ && bloomQuarter_ &&
        temporalColorHistory_[0] && temporalColorHistory_[1] && temporalDepthHistory_[0] &&
        temporalDepthHistory_[1] && sceneTargetWidth_ == width && sceneTargetHeight_ == height)
        return {};
    auto colorDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    colorDescriptor->setTextureType(MTL::TextureType2D);
    colorDescriptor->setPixelFormat(MTL::PixelFormatRGBA16Float);
    colorDescriptor->setWidth(width);
    colorDescriptor->setHeight(height);
    colorDescriptor->setStorageMode(MTL::StorageModePrivate);
    colorDescriptor->setUsage(MTL::TextureUsageRenderTarget | MTL::TextureUsageShaderRead);
    auto depthDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    depthDescriptor->setTextureType(MTL::TextureType2D);
    depthDescriptor->setPixelFormat(MTL::PixelFormatDepth32Float);
    depthDescriptor->setWidth(width);
    depthDescriptor->setHeight(height);
    depthDescriptor->setStorageMode(MTL::StorageModePrivate);
    depthDescriptor->setUsage(MTL::TextureUsageRenderTarget | MTL::TextureUsageShaderRead);
    auto color = adopt(device_->newTexture(colorDescriptor.get()));
    auto depth = adopt(device_->newTexture(depthDescriptor.get()));
    auto idDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    idDescriptor->setTextureType(MTL::TextureType2D);
    idDescriptor->setPixelFormat(MTL::PixelFormatR32Uint);
    idDescriptor->setWidth(width);
    idDescriptor->setHeight(height);
    idDescriptor->setStorageMode(MTL::StorageModePrivate);
    idDescriptor->setUsage(MTL::TextureUsageRenderTarget | MTL::TextureUsageShaderRead);
    auto ids = adopt(device_->newTexture(idDescriptor.get()));
    idDescriptor->setPixelFormat(MTL::PixelFormatRGBA16Float);
    auto motion = adopt(device_->newTexture(idDescriptor.get()));
    auto proxyNormalConfidence = adopt(device_->newTexture(idDescriptor.get()));
    auto proxyMotion = adopt(device_->newTexture(idDescriptor.get()));
    idDescriptor->setPixelFormat(MTL::PixelFormatR32Uint);
    auto proxyIds = adopt(device_->newTexture(idDescriptor.get()));
    auto proxyDepth = adopt(device_->newTexture(depthDescriptor.get()));
    colorDescriptor->setWidth(std::max<std::uint32_t>(1U, width / 2U));
    colorDescriptor->setHeight(std::max<std::uint32_t>(1U, height / 2U));
    auto bloomHalf = adopt(device_->newTexture(colorDescriptor.get()));
    colorDescriptor->setWidth(std::max<std::uint32_t>(1U, width / 4U));
    colorDescriptor->setHeight(std::max<std::uint32_t>(1U, height / 4U));
    auto bloomQuarter = adopt(device_->newTexture(colorDescriptor.get()));
    colorDescriptor->setWidth(width);
    colorDescriptor->setHeight(height);
    auto historyDepthDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    historyDepthDescriptor->setTextureType(MTL::TextureType2D);
    historyDepthDescriptor->setPixelFormat(MTL::PixelFormatR32Float);
    historyDepthDescriptor->setWidth(width);
    historyDepthDescriptor->setHeight(height);
    historyDepthDescriptor->setStorageMode(MTL::StorageModePrivate);
    historyDepthDescriptor->setUsage(MTL::TextureUsageRenderTarget | MTL::TextureUsageShaderRead);
    std::array<MetalPtr<MTL::Texture>, 2> historyColor;
    std::array<MetalPtr<MTL::Texture>, 2> historyDepth;
    for (std::size_t index = 0; index < historyColor.size(); ++index) {
        historyColor[index] = adopt(device_->newTexture(colorDescriptor.get()));
        historyDepth[index] = adopt(device_->newTexture(historyDepthDescriptor.get()));
    }
    if (!color || !depth || !ids || !motion || !proxyNormalConfidence || !proxyMotion ||
        !proxyIds || !proxyDepth || !bloomHalf || !bloomQuarter || !historyColor[0] ||
        !historyColor[1] || !historyDepth[0] || !historyDepth[1])
        return fail(ErrorCode::resourceExhausted, "Unable to allocate HDR scene targets");
    color->setLabel(NS::String::string("Scene HDR Color", NS::UTF8StringEncoding));
    depth->setLabel(NS::String::string("Scene Reverse-Z Depth", NS::UTF8StringEncoding));
    sceneHdrColor_ = std::move(color);
    sceneDepth_ = std::move(depth);
    ids->setLabel(NS::String::string("Scene Entity IDs", NS::UTF8StringEncoding));
    sceneIds_ = std::move(ids);
    motion->setLabel(NS::String::string("Scene Motion Vectors", NS::UTF8StringEncoding));
    sceneMotion_ = std::move(motion);
    proxyNormalConfidence->setLabel(
        NS::String::string("Proxy World Normal + Confidence", NS::UTF8StringEncoding));
    proxyIds->setLabel(NS::String::string("Proxy Surface IDs", NS::UTF8StringEncoding));
    proxyMotion->setLabel(NS::String::string("Proxy Motion Vectors", NS::UTF8StringEncoding));
    proxyDepth->setLabel(NS::String::string("Proxy Reverse-Z Depth", NS::UTF8StringEncoding));
    proxyNormalConfidence_ = std::move(proxyNormalConfidence);
    proxyIds_ = std::move(proxyIds);
    proxyMotion_ = std::move(proxyMotion);
    proxyDepth_ = std::move(proxyDepth);
    bloomHalf->setLabel(NS::String::string("Bloom Half Resolution", NS::UTF8StringEncoding));
    bloomQuarter->setLabel(NS::String::string("Bloom Quarter Resolution", NS::UTF8StringEncoding));
    bloomHalf_ = std::move(bloomHalf);
    bloomQuarter_ = std::move(bloomQuarter);
    for (std::size_t index = 0; index < temporalColorHistory_.size(); ++index) {
        historyColor[index]->setLabel(
            NS::String::string(index == 0 ? "Temporal Color History A" : "Temporal Color History B",
                               NS::UTF8StringEncoding));
        historyDepth[index]->setLabel(
            NS::String::string(index == 0 ? "Temporal Depth History A" : "Temporal Depth History B",
                               NS::UTF8StringEncoding));
    }
    temporalColorHistory_ = std::move(historyColor);
    temporalDepthHistory_ = std::move(historyDepth);
    temporalHistoryValid_ = false;
    sceneTargetWidth_ = width;
    sceneTargetHeight_ = height;
    return {};
}

Result<void> Renderer::ensureGaussianTargets(std::uint32_t width, std::uint32_t height) {
    if (width == 0 || height == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian render target dimensions are zero");
    if (gaussianColor_ && gaussianTargetWidth_ == width && gaussianTargetHeight_ == height)
        return {};
    auto createTexture = [&](MTL::PixelFormat format, const char* label) {
        auto descriptor = adopt(MTL::TextureDescriptor::alloc()->init());
        descriptor->setTextureType(MTL::TextureType2D);
        descriptor->setPixelFormat(format);
        descriptor->setWidth(width);
        descriptor->setHeight(height);
        descriptor->setStorageMode(MTL::StorageModePrivate);
        descriptor->setUsage(MTL::TextureUsageShaderRead | MTL::TextureUsageShaderWrite);
        auto texture = adopt(device_->newTexture(descriptor.get()));
        if (texture)
            texture->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
        return texture;
    };
    auto color = createTexture(MTL::PixelFormatRGBA16Float, "Gaussian HDR Color");
    auto depth = createTexture(MTL::PixelFormatR32Float, "Gaussian Linear Depth");
    auto ids = createTexture(MTL::PixelFormatR32Uint, "Gaussian Source IDs");
    if (!color || !depth || !ids)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate Gaussian render targets");
    gaussianColor_ = std::move(color);
    gaussianDepth_ = std::move(depth);
    gaussianIds_ = std::move(ids);
    gaussianTargetWidth_ = width;
    gaussianTargetHeight_ = height;
    return {};
}

void Renderer::setCameraMovement(scene::CameraMove movement, bool active) noexcept {
    cameraController_.setMoving(movement, active);
}

void Renderer::addCameraLookDelta(float horizontalPixels, float verticalPixels) noexcept {
    cameraController_.addLookDelta(horizontalPixels, verticalPixels);
}

void Renderer::addCameraDolly(float amount) noexcept {
    cameraController_.addDolly(amount);
}

void Renderer::clearCameraMovement() noexcept {
    cameraController_.clearMovement();
}

CameraSnapshot Renderer::cameraSnapshot() const noexcept {
    return CameraSnapshot{cameraController_.position(), cameraController_.yaw(),
                          cameraController_.pitch(), cameraVerticalFieldOfViewRadians_};
}

Result<void> Renderer::setCameraSnapshot(const CameraSnapshot& camera) {
    const bool finite = std::isfinite(camera.position.x) && std::isfinite(camera.position.y) &&
                        std::isfinite(camera.position.z) && std::isfinite(camera.yaw) &&
                        std::isfinite(camera.pitch) &&
                        std::isfinite(camera.verticalFieldOfViewRadians);
    if (!finite || camera.pitch < -1.553343F || camera.pitch > 1.553343F ||
        camera.verticalFieldOfViewRadians < 0.1745329F ||
        camera.verticalFieldOfViewRadians > 2.9670597F)
        return fail(ErrorCode::invalidArgument, "Camera snapshot is invalid");
    cameraController_.clearMovement();
    cameraController_.setPosition(camera.position);
    cameraController_.setOrientation(camera.yaw, camera.pitch);
    cameraVerticalFieldOfViewRadians_ = camera.verticalFieldOfViewRadians;
    temporalHistoryValid_ = false;
    return {};
}

RendererStatistics Renderer::statistics() const noexcept {
    return RendererStatistics{frameNumber_, completedFrames_.load(std::memory_order_relaxed),
                              lastGpuMilliseconds_.load(std::memory_order_relaxed)};
}

Result<FrameCapture> Renderer::consumeFrameCapture() {
    std::lock_guard lock(frameCaptureMutex_);
    if (!completedFrameCapture_)
        return fail(ErrorCode::notFound, "No completed frame capture is available");
    FrameCapture result = std::move(*completedFrameCapture_);
    completedFrameCapture_.reset();
    return result;
}

Result<void> Renderer::buildViewportPipeline() {
    std::string libraryPath;
    if (shaderLibraryPath_.empty()) {
        const NS::String* resourcePath = NS::Bundle::mainBundle()->resourcePath();
        if (!resourcePath) {
            return fail(ErrorCode::notFound, "Application bundle has no resource directory");
        }
        libraryPath = std::string(resourcePath->utf8String()) + "/AetherShaders.metallib";
    } else {
        libraryPath = shaderLibraryPath_.string();
    }
    NS::Error* error = nullptr;
    shaderLibrary_ = adopt(device_->newLibrary(
        NS::String::string(libraryPath.c_str(), NS::UTF8StringEncoding), &error));
    if (!shaderLibrary_) {
        const std::string message =
            error ? error->localizedDescription()->utf8String() : "Unknown Metal library error";
        return fail(ErrorCode::metal, "Unable to load offline AETHER shader library",
                    message + " · " + libraryPath);
    }
    shaderLibrary_->setLabel(NS::String::string("AETHER Offline Library", NS::UTF8StringEncoding));

    DecodedImage whiteFallback{1, 1, {255, 255, 255, 255}};
    DecodedImage normalFallback{1, 1, {128, 128, 255, 255}};
    auto white = uploadTexture(device_.get(), commandQueue_.get(), whiteFallback,
                               MTL::PixelFormatRGBA8Unorm, "Fallback White Texture");
    auto normal = uploadTexture(device_.get(), commandQueue_.get(), normalFallback,
                                MTL::PixelFormatRGBA8Unorm, "Fallback Normal Texture");
    auto fallbackSamplerDescriptor = adopt(MTL::SamplerDescriptor::alloc()->init());
    fallbackSamplerDescriptor->setLabel(
        NS::String::string("Fallback Material Sampler", NS::UTF8StringEncoding));
    fallbackSamplerDescriptor->setMinFilter(MTL::SamplerMinMagFilterLinear);
    fallbackSamplerDescriptor->setMagFilter(MTL::SamplerMinMagFilterLinear);
    fallbackSamplerDescriptor->setMipFilter(MTL::SamplerMipFilterNotMipmapped);
    fallbackSamplerDescriptor->setSAddressMode(MTL::SamplerAddressModeRepeat);
    fallbackSamplerDescriptor->setTAddressMode(MTL::SamplerAddressModeRepeat);
    auto fallbackSampler = adopt(device_->newSamplerState(fallbackSamplerDescriptor.get()));
    if (!white || !normal || !fallbackSampler)
        return fail(ErrorCode::resourceExhausted,
                    "Unable to allocate required PBR fallback resources");
    fallbackWhiteTexture_ = std::move(*white);
    fallbackNormalTexture_ = std::move(*normal);
    fallbackSampler_ = std::move(fallbackSampler);
    scene::ImageBasedLightingData neutralIbl;
    neutralIbl.irradiance.size = 1;
    neutralIbl.irradiance.linearRgb.assign(6, simd_float3{0.025F, 0.025F, 0.025F});
    scene::CubeMapLevel neutralSpecular;
    neutralSpecular.size = 1;
    neutralSpecular.linearRgb.assign(6, simd_float3{0.02F, 0.02F, 0.02F});
    neutralIbl.prefilteredSpecular.push_back(std::move(neutralSpecular));
    neutralIbl.brdfLutSize = 1;
    neutralIbl.brdfLut.push_back(simd_float2{1.0F, 0.0F});
    if (auto configured = setImageBasedLighting(neutralIbl); !configured)
        return std::unexpected(configured.error());

    auto vertex = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherViewportVertex", NS::UTF8StringEncoding)));
    auto fragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherViewportFragment", NS::UTF8StringEncoding)));
    auto sceneBackgroundFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherSceneBackgroundFragment", NS::UTF8StringEncoding)));
    auto proxyVertex = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherProxyVertex", NS::UTF8StringEncoding)));
    auto proxyFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherProxyFragment", NS::UTF8StringEncoding)));
    if (!vertex || !fragment || !sceneBackgroundFragment || !proxyVertex || !proxyFragment) {
        return fail(ErrorCode::metal, "Offline shader library is missing viewport entry points");
    }

    auto descriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    descriptor->setLabel(NS::String::string("AETHER Viewport Pipeline", NS::UTF8StringEncoding));
    descriptor->setVertexFunction(vertex.get());
    descriptor->setFragmentFunction(fragment.get());
    descriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatBGRA8Unorm_sRGB);
    descriptor->setDepthAttachmentPixelFormat(MTL::PixelFormatDepth32Float);

    std::filesystem::path cacheRoot;
    if (const char* home = std::getenv("HOME")) {
        cacheRoot = std::filesystem::path(home) / "Library/Caches/com.swayamsingal.aether";
    } else {
        cacheRoot = std::filesystem::temp_directory_path() / "com.swayamsingal.aether";
    }
    std::error_code filesystemError;
    std::filesystem::create_directories(cacheRoot, filesystemError);
    auto libraryHash = sha256File(libraryPath);
    if (!libraryHash)
        return std::unexpected(libraryHash.error());
    const auto archivePath = cacheRoot / ("AetherPipelines-" + *libraryHash + ".bin");
    const auto archiveHashPath = std::filesystem::path(archivePath.string() + ".sha256");
    auto archiveDescriptor = adopt(MTL::BinaryArchiveDescriptor::alloc()->init());
    NS::URL* archiveUrl =
        NS::URL::fileURLWithPath(NS::String::string(archivePath.c_str(), NS::UTF8StringEncoding));
    bool archiveVerified = false;
    if (!environmentFlagEnabled("MTL_DEBUG_LAYER") &&
        !environmentFlagEnabled("MTL_SHADER_VALIDATION") &&
        std::filesystem::is_regular_file(archivePath) &&
        std::filesystem::is_regular_file(archiveHashPath)) {
        std::ifstream sidecar(archiveHashPath);
        std::string expectedHash;
        sidecar >> expectedHash;
        auto actualHash = sha256File(archivePath);
        archiveVerified = actualHash && expectedHash == *actualHash;
    }
    if (archiveVerified) {
        archiveDescriptor->setUrl(archiveUrl);
    }
    binaryArchive_ = adopt(device_->newBinaryArchive(archiveDescriptor.get(), &error));
    if (!binaryArchive_ && archiveVerified) {
        std::filesystem::remove(archivePath, filesystemError);
        std::filesystem::remove(archiveHashPath, filesystemError);
        archiveDescriptor->setUrl(nullptr);
        error = nullptr;
        binaryArchive_ = adopt(device_->newBinaryArchive(archiveDescriptor.get(), &error));
    }
    if (binaryArchive_) {
        binaryArchive_->setLabel(
            NS::String::string("AETHER Pipeline Binary Archive", NS::UTF8StringEncoding));
        descriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
        error = nullptr;
        if (!binaryArchive_->addRenderPipelineFunctions(descriptor.get(), &error) && error) {
            Log::instance().write(LogLevel::warning,
                                  std::string("Pipeline archive warm-up failed: ") +
                                      error->localizedDescription()->utf8String());
        }
    }

    error = nullptr;
    viewportPipeline_ = adopt(device_->newRenderPipelineState(descriptor.get(), &error));
    if (!viewportPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create AETHER viewport pipeline", message);
    }
    descriptor->setLabel(
        NS::String::string("AETHER HDR Background Pipeline", NS::UTF8StringEncoding));
    descriptor->setFragmentFunction(sceneBackgroundFragment.get());
    descriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    descriptor->colorAttachments()->object(1)->setPixelFormat(MTL::PixelFormatR32Uint);
    descriptor->colorAttachments()->object(2)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    if (binaryArchive_) {
        error = nullptr;
        (void)binaryArchive_->addRenderPipelineFunctions(descriptor.get(), &error);
    }
    error = nullptr;
    sceneBackgroundPipeline_ = adopt(device_->newRenderPipelineState(descriptor.get(), &error));
    if (!sceneBackgroundPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown HDR pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create AETHER HDR background pipeline", message);
    }

    auto proxyDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    proxyDescriptor->setLabel(
        NS::String::string("AETHER Proxy G-buffer Pipeline", NS::UTF8StringEncoding));
    proxyDescriptor->setVertexFunction(proxyVertex.get());
    proxyDescriptor->setFragmentFunction(proxyFragment.get());
    proxyDescriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    proxyDescriptor->colorAttachments()->object(1)->setPixelFormat(MTL::PixelFormatR32Uint);
    proxyDescriptor->colorAttachments()->object(2)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    proxyDescriptor->setDepthAttachmentPixelFormat(MTL::PixelFormatDepth32Float);
    if (binaryArchive_) {
        proxyDescriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
        error = nullptr;
        (void)binaryArchive_->addRenderPipelineFunctions(proxyDescriptor.get(), &error);
    }
    error = nullptr;
    proxyPipeline_ = adopt(device_->newRenderPipelineState(proxyDescriptor.get(), &error));
    if (!proxyPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown proxy pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create proxy G-buffer pipeline", message);
    }

    auto temporalFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherTemporalResolveFragment", NS::UTF8StringEncoding)));
    if (!temporalFragment)
        return fail(ErrorCode::metal,
                    "Offline shader library is missing temporal resolve entry point");
    auto temporalDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    temporalDescriptor->setLabel(
        NS::String::string("AETHER Temporal Resolve Pipeline", NS::UTF8StringEncoding));
    temporalDescriptor->setVertexFunction(vertex.get());
    temporalDescriptor->setFragmentFunction(temporalFragment.get());
    temporalDescriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    temporalDescriptor->colorAttachments()->object(1)->setPixelFormat(MTL::PixelFormatR32Float);
    if (binaryArchive_)
        temporalDescriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
    error = nullptr;
    temporalPipeline_ = adopt(device_->newRenderPipelineState(temporalDescriptor.get(), &error));
    if (!temporalPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown temporal pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create temporal resolve pipeline", message);
    }
    auto temporalSamplerDescriptor = adopt(MTL::SamplerDescriptor::alloc()->init());
    temporalSamplerDescriptor->setMinFilter(MTL::SamplerMinMagFilterLinear);
    temporalSamplerDescriptor->setMagFilter(MTL::SamplerMinMagFilterLinear);
    temporalSamplerDescriptor->setSAddressMode(MTL::SamplerAddressModeClampToEdge);
    temporalSamplerDescriptor->setTAddressMode(MTL::SamplerAddressModeClampToEdge);
    temporalSampler_ = adopt(device_->newSamplerState(temporalSamplerDescriptor.get()));
    if (!temporalSampler_)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate temporal sampler");
    auto bloomFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherBloomDownsampleFragment", NS::UTF8StringEncoding)));
    if (!bloomFragment)
        return fail(ErrorCode::metal, "Offline shader library is missing bloom entry point");
    auto bloomDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    bloomDescriptor->setLabel(
        NS::String::string("AETHER Bloom Downsample Pipeline", NS::UTF8StringEncoding));
    bloomDescriptor->setVertexFunction(vertex.get());
    bloomDescriptor->setFragmentFunction(bloomFragment.get());
    bloomDescriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    if (binaryArchive_)
        bloomDescriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
    error = nullptr;
    bloomPipeline_ = adopt(device_->newRenderPipelineState(bloomDescriptor.get(), &error));
    if (!bloomPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown bloom pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create bloom pipeline", message);
    }
    auto gizmoVertex = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherGizmoVertex", NS::UTF8StringEncoding)));
    auto gizmoFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherGizmoFragment", NS::UTF8StringEncoding)));
    if (!gizmoVertex || !gizmoFragment)
        return fail(ErrorCode::metal, "Offline shader library is missing gizmo entry points");
    auto gizmoDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    gizmoDescriptor->setLabel(
        NS::String::string("AETHER Translation Gizmo Pipeline", NS::UTF8StringEncoding));
    gizmoDescriptor->setVertexFunction(gizmoVertex.get());
    gizmoDescriptor->setFragmentFunction(gizmoFragment.get());
    gizmoDescriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    gizmoDescriptor->colorAttachments()->object(1)->setPixelFormat(MTL::PixelFormatR32Uint);
    gizmoDescriptor->colorAttachments()->object(2)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    gizmoDescriptor->setDepthAttachmentPixelFormat(MTL::PixelFormatDepth32Float);
    if (binaryArchive_)
        gizmoDescriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
    error = nullptr;
    gizmoPipeline_ = adopt(device_->newRenderPipelineState(gizmoDescriptor.get(), &error));
    if (!gizmoPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown gizmo pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create translation gizmo pipeline", message);
    }

    auto pbrVertex = adopt(
        shaderLibrary_->newFunction(NS::String::string("aetherPbrVertex", NS::UTF8StringEncoding)));
    auto pbrFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherPbrFragment", NS::UTF8StringEncoding)));
    if (!pbrVertex || !pbrFragment) {
        return fail(ErrorCode::metal, "Offline shader library is missing PBR entry points");
    }
    auto shadowVertex = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherShadowVertex", NS::UTF8StringEncoding)));
    auto shadowFragment = adopt(shaderLibrary_->newFunction(
        NS::String::string("aetherShadowFragment", NS::UTF8StringEncoding)));
    if (!shadowVertex || !shadowFragment)
        return fail(ErrorCode::metal,
                    "Offline shader library is missing shadow caster entry points");
    auto shadowDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    shadowDescriptor->setLabel(
        NS::String::string("AETHER Cascaded Shadow Pipeline", NS::UTF8StringEncoding));
    shadowDescriptor->setVertexFunction(shadowVertex.get());
    shadowDescriptor->setFragmentFunction(shadowFragment.get());
    shadowDescriptor->setDepthAttachmentPixelFormat(MTL::PixelFormatDepth32Float);
    error = nullptr;
    shadowPipeline_ = adopt(device_->newRenderPipelineState(shadowDescriptor.get(), &error));
    if (!shadowPipeline_)
        return fail(ErrorCode::metal, "Unable to create cascaded shadow pipeline");
    auto shadowTextureDescriptor = adopt(MTL::TextureDescriptor::alloc()->init());
    shadowTextureDescriptor->setTextureType(MTL::TextureType2DArray);
    shadowTextureDescriptor->setPixelFormat(MTL::PixelFormatDepth32Float);
    shadowTextureDescriptor->setWidth(shadowConfig_.resolution);
    shadowTextureDescriptor->setHeight(shadowConfig_.resolution);
    shadowTextureDescriptor->setArrayLength(shadowConfig_.cascadeCount);
    shadowTextureDescriptor->setStorageMode(MTL::StorageModePrivate);
    shadowTextureDescriptor->setUsage(MTL::TextureUsageRenderTarget | MTL::TextureUsageShaderRead);
    directionalShadowMap_ = adopt(device_->newTexture(shadowTextureDescriptor.get()));
    shadowTextureDescriptor->setWidth(localShadowConfig_.resolution);
    shadowTextureDescriptor->setHeight(localShadowConfig_.resolution);
    shadowTextureDescriptor->setArrayLength(AETHER_LOCAL_SHADOW_SLICE_COUNT);
    localShadowMap_ = adopt(device_->newTexture(shadowTextureDescriptor.get()));
    auto shadowSamplerDescriptor = adopt(MTL::SamplerDescriptor::alloc()->init());
    shadowSamplerDescriptor->setCompareFunction(MTL::CompareFunctionLessEqual);
    shadowSamplerDescriptor->setMinFilter(MTL::SamplerMinMagFilterLinear);
    shadowSamplerDescriptor->setMagFilter(MTL::SamplerMinMagFilterLinear);
    shadowSamplerDescriptor->setSAddressMode(MTL::SamplerAddressModeClampToEdge);
    shadowSamplerDescriptor->setTAddressMode(MTL::SamplerAddressModeClampToEdge);
    shadowComparisonSampler_ = adopt(device_->newSamplerState(shadowSamplerDescriptor.get()));
    if (!directionalShadowMap_ || !localShadowMap_ || !shadowComparisonSampler_)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate shadow resources");
    directionalShadowMap_->setLabel(
        NS::String::string("Directional Shadow Cascades", NS::UTF8StringEncoding));
    localShadowMap_->setLabel(NS::String::string("Local Shadow Slices", NS::UTF8StringEncoding));
    MTL::CommandBuffer* shadowClearBuffer = commandQueue_->commandBuffer();
    if (!shadowClearBuffer)
        return fail(ErrorCode::metal, "Unable to create shadow initialization command buffer");
    for (std::uint32_t cascade = 0; cascade < shadowConfig_.cascadeCount; ++cascade) {
        MTL::RenderPassDescriptor* clearPass = MTL::RenderPassDescriptor::renderPassDescriptor();
        clearPass->depthAttachment()->setTexture(directionalShadowMap_.get());
        clearPass->depthAttachment()->setSlice(cascade);
        clearPass->depthAttachment()->setLoadAction(MTL::LoadActionClear);
        clearPass->depthAttachment()->setStoreAction(MTL::StoreActionStore);
        clearPass->depthAttachment()->setClearDepth(1.0);
        auto* clearEncoder = shadowClearBuffer->renderCommandEncoder(clearPass);
        if (!clearEncoder)
            return fail(ErrorCode::metal, "Unable to encode shadow initialization");
        clearEncoder->setLabel(NS::String::string("Shadow Cascade Clear", NS::UTF8StringEncoding));
        clearEncoder->endEncoding();
    }
    for (std::uint32_t slice = 0; slice < AETHER_LOCAL_SHADOW_SLICE_COUNT; ++slice) {
        MTL::RenderPassDescriptor* clearPass = MTL::RenderPassDescriptor::renderPassDescriptor();
        clearPass->depthAttachment()->setTexture(localShadowMap_.get());
        clearPass->depthAttachment()->setSlice(slice);
        clearPass->depthAttachment()->setLoadAction(MTL::LoadActionClear);
        clearPass->depthAttachment()->setStoreAction(MTL::StoreActionStore);
        clearPass->depthAttachment()->setClearDepth(1.0);
        auto* clearEncoder = shadowClearBuffer->renderCommandEncoder(clearPass);
        if (!clearEncoder)
            return fail(ErrorCode::metal, "Unable to encode local shadow initialization");
        clearEncoder->setLabel(NS::String::string("Local Shadow Clear", NS::UTF8StringEncoding));
        clearEncoder->endEncoding();
    }
    shadowClearBuffer->commit();
    shadowClearBuffer->waitUntilCompleted();

    auto shadowDepthDescriptor = adopt(MTL::DepthStencilDescriptor::alloc()->init());
    shadowDepthDescriptor->setLabel(
        NS::String::string("AETHER Shadow Depth Less", NS::UTF8StringEncoding));
    shadowDepthDescriptor->setDepthCompareFunction(MTL::CompareFunctionLess);
    shadowDepthDescriptor->setDepthWriteEnabled(true);
    shadowDepthState_ = adopt(device_->newDepthStencilState(shadowDepthDescriptor.get()));
    if (!shadowDepthState_)
        return fail(ErrorCode::resourceExhausted, "Unable to allocate shadow depth state");
    auto pbrDescriptor = adopt(MTL::RenderPipelineDescriptor::alloc()->init());
    pbrDescriptor->setLabel(NS::String::string("AETHER PBR Pipeline", NS::UTF8StringEncoding));
    pbrDescriptor->setVertexFunction(pbrVertex.get());
    pbrDescriptor->setFragmentFunction(pbrFragment.get());
    pbrDescriptor->colorAttachments()->object(0)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    pbrDescriptor->colorAttachments()->object(1)->setPixelFormat(MTL::PixelFormatR32Uint);
    pbrDescriptor->colorAttachments()->object(2)->setPixelFormat(MTL::PixelFormatRGBA16Float);
    pbrDescriptor->setDepthAttachmentPixelFormat(MTL::PixelFormatDepth32Float);
    if (binaryArchive_) {
        pbrDescriptor->setBinaryArchives(NS::Array::array(binaryArchive_.get()));
        error = nullptr;
        if (!binaryArchive_->addRenderPipelineFunctions(pbrDescriptor.get(), &error) && error) {
            Log::instance().write(LogLevel::warning,
                                  std::string("PBR archive warm-up failed: ") +
                                      error->localizedDescription()->utf8String());
        }
    }
    error = nullptr;
    pbrPipeline_ = adopt(device_->newRenderPipelineState(pbrDescriptor.get(), &error));
    if (!pbrPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown PBR pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create AETHER PBR pipeline", message);
    }
    auto* blendAttachment = pbrDescriptor->colorAttachments()->object(0);
    blendAttachment->setBlendingEnabled(true);
    blendAttachment->setSourceRGBBlendFactor(MTL::BlendFactorSourceAlpha);
    blendAttachment->setDestinationRGBBlendFactor(MTL::BlendFactorOneMinusSourceAlpha);
    blendAttachment->setSourceAlphaBlendFactor(MTL::BlendFactorOne);
    blendAttachment->setDestinationAlphaBlendFactor(MTL::BlendFactorOneMinusSourceAlpha);
    pbrDescriptor->setLabel(
        NS::String::string("AETHER PBR Alpha Blend Pipeline", NS::UTF8StringEncoding));
    if (binaryArchive_) {
        error = nullptr;
        (void)binaryArchive_->addRenderPipelineFunctions(pbrDescriptor.get(), &error);
    }
    error = nullptr;
    pbrBlendPipeline_ = adopt(device_->newRenderPipelineState(pbrDescriptor.get(), &error));
    if (!pbrBlendPipeline_) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown blend pipeline compilation error";
        return fail(ErrorCode::metal, "Unable to create AETHER alpha blend pipeline", message);
    }

    auto depthDescriptor = adopt(MTL::DepthStencilDescriptor::alloc()->init());
    depthDescriptor->setLabel(NS::String::string("AETHER Reverse-Z Depth", NS::UTF8StringEncoding));
    depthDescriptor->setDepthCompareFunction(MTL::CompareFunctionGreater);
    depthDescriptor->setDepthWriteEnabled(true);
    reverseZDepthState_ = adopt(device_->newDepthStencilState(depthDescriptor.get()));
    if (!reverseZDepthState_) {
        return fail(ErrorCode::metal, "Unable to create reverse-Z depth state");
    }
    depthDescriptor->setLabel(
        NS::String::string("AETHER Gaussian Composition Depth", NS::UTF8StringEncoding));
    depthDescriptor->setDepthCompareFunction(MTL::CompareFunctionGreaterEqual);
    gaussianCompositionDepthState_ = adopt(device_->newDepthStencilState(depthDescriptor.get()));
    if (!gaussianCompositionDepthState_)
        return fail(ErrorCode::resourceExhausted,
                    "Unable to create Gaussian composition depth state");
    depthDescriptor->setDepthCompareFunction(MTL::CompareFunctionGreater);
    depthDescriptor->setLabel(
        NS::String::string("AETHER Reverse-Z Read-Only Depth", NS::UTF8StringEncoding));
    depthDescriptor->setDepthWriteEnabled(false);
    reverseZReadOnlyDepthState_ = adopt(device_->newDepthStencilState(depthDescriptor.get()));
    if (!reverseZReadOnlyDepthState_)
        return fail(ErrorCode::metal, "Unable to create read-only reverse-Z depth state");
    if (binaryArchive_) {
        const std::string suffix = ".tmp-" + std::to_string(reinterpret_cast<std::uintptr_t>(this));
        const auto temporaryArchive = std::filesystem::path(archivePath.string() + suffix);
        const auto temporaryHash = std::filesystem::path(archiveHashPath.string() + suffix);
        std::filesystem::remove(temporaryArchive, filesystemError);
        std::filesystem::remove(temporaryHash, filesystemError);
        NS::URL* temporaryUrl = NS::URL::fileURLWithPath(
            NS::String::string(temporaryArchive.c_str(), NS::UTF8StringEncoding));
        error = nullptr;
        if (!binaryArchive_->serializeToURL(temporaryUrl, &error)) {
            Log::instance().write(
                LogLevel::warning,
                std::string("Pipeline archive serialization failed: ") +
                    (error ? error->localizedDescription()->utf8String() : "unknown Metal error"));
        } else {
            auto serializedHash = sha256File(temporaryArchive);
            std::ofstream sidecar(temporaryHash, std::ios::trunc);
            if (serializedHash)
                sidecar << *serializedHash << "  " << archivePath.filename().string() << '\n';
            sidecar.close();
            if (!serializedHash || !sidecar) {
                Log::instance().write(LogLevel::warning,
                                      "Unable to hash the serialized pipeline archive");
            } else {
                filesystemError.clear();
                std::filesystem::rename(temporaryArchive, archivePath, filesystemError);
                if (!filesystemError)
                    std::filesystem::rename(temporaryHash, archiveHashPath, filesystemError);
                if (filesystemError)
                    Log::instance().write(LogLevel::warning,
                                          "Unable to atomically publish the pipeline archive");
            }
        }
        std::filesystem::remove(temporaryArchive, filesystemError);
        std::filesystem::remove(temporaryHash, filesystemError);
    }
    return {};
}

Result<MetalPtr<MTL::Buffer>> Renderer::uploadPrivateBuffer(const void* bytes, std::size_t size,
                                                            const char* labelText) {
    if (!bytes || size == 0) {
        return fail(ErrorCode::invalidArgument, "Cannot upload an empty GPU buffer", labelText);
    }
    auto destination = adopt(device_->newBuffer(size, MTL::ResourceStorageModePrivate));
    auto staging = adopt(device_->newBuffer(bytes, size, MTL::ResourceStorageModeShared));
    if (!destination || !staging) {
        return fail(ErrorCode::resourceExhausted, "Metal buffer allocation failed", labelText);
    }
    destination->setLabel(NS::String::string(labelText, NS::UTF8StringEncoding));
    MTL::CommandBuffer* commandBuffer = commandQueue_->commandBuffer();
    MTL::BlitCommandEncoder* blit = commandBuffer ? commandBuffer->blitCommandEncoder() : nullptr;
    if (!commandBuffer || !blit) {
        return fail(ErrorCode::metal, "Unable to create mesh upload command encoder", labelText);
    }
    blit->setLabel(NS::String::string("Mesh Upload", NS::UTF8StringEncoding));
    blit->copyFromBuffer(staging.get(), 0, destination.get(), 0, size);
    blit->endEncoding();
    commandBuffer->addCompletedHandler([staging](MTL::CommandBuffer*) { (void)staging; });
    commandBuffer->commit();
    return destination;
}

DeviceCapabilities Renderer::inspect(MTL::Device* device) {
    DeviceCapabilities result;
    if (const NS::String* name = device->name()) {
        result.name = name->utf8String();
    }
    const std::array<std::pair<MTL::GPUFamily, std::uint32_t>, 8> families{{
        {MTL::GPUFamilyApple1, 1},
        {MTL::GPUFamilyApple2, 2},
        {MTL::GPUFamilyApple3, 3},
        {MTL::GPUFamilyApple4, 4},
        {MTL::GPUFamilyApple5, 5},
        {MTL::GPUFamilyApple6, 6},
        {MTL::GPUFamilyApple7, 7},
        {MTL::GPUFamilyApple8, 8},
    }};
    for (const auto& [family, number] : families) {
        if (device->supportsFamily(family)) {
            result.highestAppleFamily = number;
        }
    }
    result.rayTracing = device->supportsRaytracing();
    result.dynamicLibraries = device->supportsDynamicLibraries();
    // The vendored metal-cpp snapshot predates Metal 4 declarations. This remains false until
    // the compatibility layer is updated and every Metal 4 feature has a Metal 3 fallback.
    result.metal4PathAvailable = false;
    return result;
}

} // namespace aether::metal
