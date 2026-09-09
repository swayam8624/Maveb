#pragma once

#include <aether/core/Clock.hpp>
#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/mesh/MeshAsset.hpp>
#include <aether/metal/FrameContext.hpp>
#include <aether/metal/GaussianPipeline.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <aether/scene/CameraController.hpp>
#include <aether/scene/ImageBasedLighting.hpp>
#include <aether/scene/Lighting.hpp>
#include <aether/scene/Shadows.hpp>
#include <shared/AetherShaderTypes.h>

#include <Metal/Metal.hpp>
#include <MetalKit/MetalKit.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <dispatch/dispatch.h>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace aether::metal {

struct DeviceCapabilities {
    std::string name;
    std::uint32_t highestAppleFamily{};
    bool rayTracing{};
    bool dynamicLibraries{};
    bool metal4PathAvailable{};
};

struct RendererStatistics {
    std::uint64_t submittedFrames{};
    std::uint64_t completedFrames{};
    double lastGpuMilliseconds{};
};

struct ProxyMeshStatistics {
    std::uint32_t vertices{};
    std::uint32_t triangles{};
};

struct FrameCapture final {
    std::uint32_t width{};
    std::uint32_t height{};
    std::vector<std::byte> bgra8;
};

struct MeshEntitySnapshot final {
    std::uint32_t id{};
    std::string name;
    scene::Transform worldTransform;
    bool overridden{};
};

struct MaterialSnapshot final {
    std::uint32_t id{};
    std::string name;
    simd_float4 baseColor{1.0F, 1.0F, 1.0F, 1.0F};
    simd_float3 emissive{};
    float metallic{1.0F};
    float roughness{1.0F};
    float normalScale{1.0F};
    float occlusionStrength{1.0F};
    float alphaCutoff{0.5F};
    bool overridden{};
};

struct CameraSnapshot final {
    simd_float3 position{0.0F, 0.0F, 2.5F};
    float yaw{};
    float pitch{};
    float verticalFieldOfViewRadians{1.0471976F};
};

class Renderer final {
  public:
    static Result<std::unique_ptr<Renderer>> create(MTL::Device* device,
                                                    std::filesystem::path shaderLibraryPath = {});
    ~Renderer();

    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;

    void draw(MTK::View* view) noexcept;
    void drawableSizeWillChange(CGSize size) noexcept;
    [[nodiscard]] Result<void> loadGltf(const std::filesystem::path& path);
    /// Adds one glTF asset as editable dynamic entities without replacing the captured world.
    /// The current release accepts one attached glTF asset per captured scene.
    [[nodiscard]] Result<void> attachDynamicGltf(const std::filesystem::path& path);
    void detachDynamicGltf() noexcept;
    [[nodiscard]] Result<void> loadPly(const std::filesystem::path& path);
    [[nodiscard]] Result<void> loadAether(const std::filesystem::path& path);

    /// Replaces the active captured Gaussian scene directly from a validated in-memory asset.
    /// Used by persistent-reality state reloads after authored edits.
    [[nodiscard]] Result<void> loadGaussianAsset(const gaussian::GaussianAsset& asset);
    void clearCapturedGaussianScene() noexcept;

    /// Validates a source-order subset translation against the currently loaded shared GPU buffer
    /// without mutating visible state.
    [[nodiscard]] Result<void>
    validateGaussianTranslation(std::span<const std::uint32_t> gaussianIndices,
                                simd_float3 translationDelta) const;

    /// Waits until every in-flight frame has released the shared Gaussian buffer, applies one
    /// transactional source-order subset translation, invalidates temporal history, then resumes
    /// frame submission. This is the renderer seam used by persistent local Gaussian edits.
    [[nodiscard]] Result<void> translateGaussians(std::span<const std::uint32_t> gaussianIndices,
                                                  simd_float3 translationDelta);

    [[nodiscard]] Result<void> selectAnimation(std::size_t clipIndex, bool loop = true);
    void setAnimationPlaying(bool playing) noexcept {
        animationPlaying_ = playing;
    }
    void seekAnimation(float seconds) noexcept;
    [[nodiscard]] Result<void> setAnimationPlayback(std::optional<std::size_t> clipIndex,
                                                    float seconds, bool playing, bool loop);
    [[nodiscard]] std::size_t animationClipCount() const noexcept;
    void setExposureStops(float stops) noexcept;
    [[nodiscard]] Result<void> setLights(std::vector<scene::Light> lights);
    [[nodiscard]] const std::vector<scene::Light>& lights() const noexcept {
        return lights_;
    }
    [[nodiscard]] Result<void> setLight(std::uint32_t lightId, const scene::Light& light);
    [[nodiscard]] Result<std::uint32_t> addLight(const scene::Light& light);
    [[nodiscard]] Result<void> removeLight(std::uint32_t lightId);
    [[nodiscard]] Result<void> setImageBasedLighting(const scene::ImageBasedLightingData& data,
                                                     float intensity = 1.0F);
    [[nodiscard]] float exposureStops() const noexcept {
        return exposureStops_;
    }
    /// Input: top-left-origin drawable pixel coordinate.
    /// Output: 1-based Gaussian source ID, or zero for background.
    [[nodiscard]] Result<std::uint32_t> pickGaussian(std::uint32_t x, std::uint32_t y);
    /// Returns the canonical proxy surface ID at a drawable pixel, or zero for no proxy.
    [[nodiscard]] Result<std::uint32_t> pickProxy(std::uint32_t x, std::uint32_t y);
    /// Returns a 1-based visible mesh-instance ID, or zero for background.
    [[nodiscard]] Result<std::uint32_t> pickMesh(std::uint32_t x, std::uint32_t y);
    /// Immutable names ordered by their 1-based mesh entity IDs.
    [[nodiscard]] std::vector<std::string> meshEntityNames() const;
    [[nodiscard]] Result<MeshEntitySnapshot> meshEntitySnapshot(std::uint32_t entityId) const;
    [[nodiscard]] Result<void> setMeshEntityTransform(std::uint32_t entityId,
                                                      const scene::Transform& transform);
    [[nodiscard]] Result<void> clearMeshEntityTransform(std::uint32_t entityId);
    [[nodiscard]] Result<void> setSelectedMeshEntity(std::uint32_t entityId);
    [[nodiscard]] Result<std::uint32_t> pickGizmoAxis(std::uint32_t x, std::uint32_t y);
    [[nodiscard]] Result<simd_float4> sampleMotionVector(std::uint32_t x, std::uint32_t y);
    [[nodiscard]] Result<MeshEntitySnapshot> translateSelectedMesh(std::uint32_t axis,
                                                                   float worldDistance);
    [[nodiscard]] Result<MeshEntitySnapshot> translateSelectedMeshPixels(std::uint32_t axis,
                                                                         float pixelDistance);
    [[nodiscard]] Result<MeshEntitySnapshot> rotateSelectedMeshPixels(std::uint32_t axis,
                                                                      float pixelDistance);
    [[nodiscard]] Result<MeshEntitySnapshot> scaleSelectedMeshPixels(std::uint32_t axis,
                                                                     float pixelDistance);
    void setGizmoMode(std::uint32_t mode) noexcept {
        gizmoMode_ = std::min(mode, 2U);
    }
    [[nodiscard]] std::vector<MaterialSnapshot> materialSnapshots() const;
    [[nodiscard]] Result<void> setMaterialOverride(const MaterialSnapshot& material);
    [[nodiscard]] Result<void> clearMaterialOverride(std::uint32_t materialId);
    void setCameraMovement(scene::CameraMove movement, bool active) noexcept;
    void addCameraLookDelta(float horizontalPixels, float verticalPixels) noexcept;
    void addCameraDolly(float amount) noexcept;
    void clearCameraMovement() noexcept;
    [[nodiscard]] CameraSnapshot cameraSnapshot() const noexcept;
    [[nodiscard]] Result<void> setCameraSnapshot(const CameraSnapshot& camera);
    void setGaussianDebugMode(std::uint32_t mode) noexcept {
        gaussianDebugMode_ = mode <= 6 ? mode : 0;
    }
    void setShadowDebugMode(std::uint32_t mode, std::uint32_t slice) noexcept {
        shadowDebugMode_ = mode <= 2 ? mode : 0;
        shadowDebugSlice_ = mode == 1 ? std::min(slice, 3U) : std::min(slice, 11U);
    }
    [[nodiscard]] const DeviceCapabilities& capabilities() const noexcept {
        return capabilities_;
    }
    [[nodiscard]] RendererStatistics statistics() const noexcept;
    /// Returns zero counts when the active scene has no canonical proxy mesh.
    [[nodiscard]] ProxyMeshStatistics proxyMeshStatistics() const noexcept {
        return {proxyVertexCount_, proxyIndexCount_ / 3U};
    }
    /// Requests an asynchronous copy of the next fully presented frame.
    void requestFrameCapture() noexcept {
        frameCaptureRequested_.store(true);
    }
    /// Returns and consumes the most recently completed capture.
    [[nodiscard]] Result<FrameCapture> consumeFrameCapture();

  private:
    Renderer(MTL::Device* device, std::filesystem::path shaderLibraryPath);
    [[nodiscard]] Result<void> loadGltfAsset(const std::filesystem::path& path,
                                             bool preserveCapturedWorld);
    [[nodiscard]] Result<void> buildViewportPipeline();
    [[nodiscard]] Result<void> ensureGaussianTargets(std::uint32_t width, std::uint32_t height);
    [[nodiscard]] Result<void> ensureSceneTargets(std::uint32_t width, std::uint32_t height);
    [[nodiscard]] Result<MetalPtr<MTL::Buffer>>
    uploadPrivateBuffer(const void* bytes, std::size_t size, const char* label);
    [[nodiscard]] static DeviceCapabilities inspect(MTL::Device* device);

    MetalPtr<MTL::Device> device_;
    MetalPtr<MTL::CommandQueue> commandQueue_;
    MetalPtr<MTL::Library> shaderLibrary_;
    MetalPtr<MTL::BinaryArchive> binaryArchive_;
    MetalPtr<MTL::RenderPipelineState> viewportPipeline_;
    MetalPtr<MTL::RenderPipelineState> temporalPipeline_;
    MetalPtr<MTL::RenderPipelineState> bloomPipeline_;
    MetalPtr<MTL::RenderPipelineState> gizmoPipeline_;
    MetalPtr<MTL::RenderPipelineState> sceneBackgroundPipeline_;
    MetalPtr<MTL::RenderPipelineState> proxyPipeline_;
    MetalPtr<MTL::RenderPipelineState> pbrPipeline_;
    MetalPtr<MTL::RenderPipelineState> pbrBlendPipeline_;
    MetalPtr<MTL::RenderPipelineState> shadowPipeline_;
    MetalPtr<MTL::DepthStencilState> reverseZDepthState_;
    MetalPtr<MTL::DepthStencilState> reverseZReadOnlyDepthState_;
    MetalPtr<MTL::DepthStencilState> gaussianCompositionDepthState_;
    MetalPtr<MTL::DepthStencilState> shadowDepthState_;
    MetalPtr<MTL::Texture> fallbackWhiteTexture_;
    MetalPtr<MTL::Texture> fallbackNormalTexture_;
    MetalPtr<MTL::SamplerState> fallbackSampler_;
    MetalPtr<MTL::Texture> irradianceTexture_;
    MetalPtr<MTL::Texture> specularEnvironmentTexture_;
    MetalPtr<MTL::Texture> brdfLutTexture_;
    MetalPtr<MTL::SamplerState> environmentSampler_;
    MetalPtr<MTL::SamplerState> temporalSampler_;
    MetalPtr<MTL::Texture> directionalShadowMap_;
    MetalPtr<MTL::Texture> localShadowMap_;
    MetalPtr<MTL::SamplerState> shadowComparisonSampler_;
    scene::DirectionalShadowConfig shadowConfig_;
    scene::LocalShadowConfig localShadowConfig_;
    float iblMaximumMip_{};
    float iblIntensity_{1.0F};
    dispatch_semaphore_t frameSemaphore_{};
    DeviceCapabilities capabilities_;
    CGSize drawableSize_{};
    std::uint64_t frameNumber_{};
    std::array<std::unique_ptr<FrameContext>, 3> frameContexts_;
    std::atomic<std::uint64_t> completedFrames_{};
    std::atomic<double> lastGpuMilliseconds_{};
    std::atomic<bool> frameCaptureRequested_{};
    std::mutex frameCaptureMutex_;
    std::optional<FrameCapture> completedFrameCapture_;

    struct GpuMeshPrimitive {
        MetalPtr<MTL::Buffer> vertices;
        MetalPtr<MTL::Buffer> indices;
        std::uint32_t indexCount{};
        std::size_t materialIndex{};
        simd_float3 localBoundsCenter{};
        MetalPtr<MTL::Buffer> morphDeltas;
        std::uint32_t morphTargetCount{};
        std::uint32_t vertexCount{};
    };
    struct GpuMeshInstance {
        std::size_t primitiveIndex{};
        simd_float4x4 worldTransform{matrix_identity_float4x4};
        simd_float4x4 previousWorldTransform{matrix_identity_float4x4};
        simd_float3 worldBoundsCenter{};
        bool mirrored{};
        std::size_t nodeIndex{};
        std::optional<std::size_t> skinIndex;
        std::vector<float> morphWeights;
        std::vector<float> previousMorphWeights;
        std::optional<scene::Transform> transformOverride;
    };
    struct GpuTexture {
        MetalPtr<MTL::Texture> srgb;
        MetalPtr<MTL::Texture> linear;
        MetalPtr<MTL::SamplerState> sampler;
    };
    struct GpuMaterial {
        std::string name;
        AetherMaterialUniforms material{};
        AetherMaterialUniforms importedMaterial{};
        bool overridden{};
        bool doubleSided{};
        bool alphaBlend{};
        std::array<MTL::Texture*, 5> textures{};
        std::array<MTL::SamplerState*, 5> samplers{};
    };
    std::vector<GpuMeshPrimitive> meshPrimitives_;
    std::vector<GpuMeshInstance> meshInstances_;
    std::vector<GpuTexture> meshTextures_;
    std::vector<GpuMaterial> meshMaterials_;
    std::optional<mesh::MeshAsset> meshAnimationAsset_;
    std::vector<simd_float4x4> meshWorldTransforms_;
    std::vector<simd_float4x4> previousMeshWorldTransforms_;
    std::optional<std::size_t> selectedAnimation_;
    float animationSeconds_{};
    bool animationLoop_{true};
    bool animationPlaying_{true};
    float exposureStops_{};
    std::vector<scene::Light> lights_;
    std::unique_ptr<GaussianPipeline> gaussianPipeline_;
    MetalPtr<MTL::Texture> gaussianColor_;
    MetalPtr<MTL::Texture> gaussianDepth_;
    MetalPtr<MTL::Texture> gaussianIds_;
    MetalPtr<MTL::Buffer> proxyVertices_;
    MetalPtr<MTL::Buffer> proxyIndices_;
    std::uint32_t proxyVertexCount_{};
    std::uint32_t proxyIndexCount_{};
    MetalPtr<MTL::Texture> proxyNormalConfidence_;
    MetalPtr<MTL::Texture> proxyIds_;
    MetalPtr<MTL::Texture> proxyMotion_;
    MetalPtr<MTL::Texture> proxyDepth_;
    MetalPtr<MTL::Texture> sceneHdrColor_;
    MetalPtr<MTL::Texture> sceneDepth_;
    MetalPtr<MTL::Texture> sceneIds_;
    MetalPtr<MTL::Texture> sceneMotion_;
    MetalPtr<MTL::Texture> bloomHalf_;
    MetalPtr<MTL::Texture> bloomQuarter_;
    std::array<MetalPtr<MTL::Texture>, 2> temporalColorHistory_;
    std::array<MetalPtr<MTL::Texture>, 2> temporalDepthHistory_;
    simd_float4x4 previousViewProjection_{matrix_identity_float4x4};
    bool temporalHistoryValid_{};
    std::uint32_t sceneTargetWidth_{};
    std::uint32_t sceneTargetHeight_{};
    std::uint32_t gaussianTargetWidth_{};
    std::uint32_t gaussianTargetHeight_{};
    std::filesystem::path shaderLibraryPath_;
    scene::CameraController cameraController_;
    float cameraVerticalFieldOfViewRadians_{1.0471976F};
    std::uint32_t gaussianDebugMode_{};
    std::uint32_t shadowDebugMode_{};
    std::uint32_t shadowDebugSlice_{};
    std::uint32_t selectedMeshEntity_{};
    std::uint32_t gizmoMode_{};
    Clock::TimePoint previousFrameTime_ = Clock::now();
};

} // namespace aether::metal
