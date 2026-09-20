#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/hybrid/ProxyMeshCodec.hpp>
#include <aether/metal/FrameContext.hpp>
#include <aether/metal/GaussianPipeline.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <aether/metal/Renderer.hpp>
#include <aether/package/Package.hpp>

#include <Foundation/Foundation.hpp>
#include <Metal/Metal.hpp>

#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <span>
#include <string_view>
#include <thread>
#include <vector>

namespace {
aether::metal::MetalPtr<MTL::Texture> makeTexture(MTL::Device* device, MTL::PixelFormat format,
                                                  std::size_t width, std::size_t height) {
    auto descriptor = aether::metal::adopt(MTL::TextureDescriptor::alloc()->init());
    descriptor->setTextureType(MTL::TextureType2D);
    descriptor->setPixelFormat(format);
    descriptor->setWidth(width);
    descriptor->setHeight(height);
    descriptor->setStorageMode(MTL::StorageModeShared);
    descriptor->setUsage(MTL::TextureUsageShaderRead | MTL::TextureUsageShaderWrite);
    return aether::metal::adopt(device->newTexture(descriptor.get()));
}

bool writeCaptureArtifact(const aether::metal::FrameCapture& capture, std::string_view name) {
    const std::filesystem::path root = AETHER_TEST_ARTIFACT_DIR;
    std::error_code error;
    std::filesystem::create_directories(root, error);
    if (error)
        return false;
    const auto imagePath = root / (std::string(name) + ".ppm");
    std::ofstream image(imagePath, std::ios::binary | std::ios::trunc);
    if (!image)
        return false;
    image << "P6\n" << capture.width << ' ' << capture.height << "\n255\n";
    for (std::size_t pixel = 0; pixel < capture.bgra8.size(); pixel += 4) {
        const char rgb[] = {static_cast<char>(capture.bgra8[pixel + 2]),
                            static_cast<char>(capture.bgra8[pixel + 1]),
                            static_cast<char>(capture.bgra8[pixel])};
        image.write(rgb, sizeof(rgb));
    }
    image.close();
    if (!image)
        return false;
    const auto digest = aether::package::Sha256::hash(capture.bgra8);
    std::ofstream sidecar(root / (std::string(name) + ".sha256"), std::ios::trunc);
    if (!sidecar)
        return false;
    sidecar << aether::package::Sha256::hex(digest) << "  " << imagePath.filename().string()
            << '\n';
    return static_cast<bool>(sidecar);
}

bool resetCaptureArtifacts() {
    const std::filesystem::path root = AETHER_TEST_ARTIFACT_DIR;
    std::error_code error;
    std::filesystem::remove_all(root, error);
    if (error)
        return false;
    std::filesystem::create_directories(root, error);
    return !error;
}

struct CaptureMetrics {
    double meanLuminance{};
    std::size_t brightPixels{};
    std::size_t darkPixels{};
    std::size_t opaquePixels{};
};

CaptureMetrics measureCapture(const aether::metal::FrameCapture& capture) {
    CaptureMetrics metrics;
    double luminanceSum = 0.0;
    for (std::size_t pixel = 0; pixel < capture.bgra8.size(); pixel += 4) {
        const double blue = static_cast<std::uint8_t>(capture.bgra8[pixel]) / 255.0;
        const double green = static_cast<std::uint8_t>(capture.bgra8[pixel + 1]) / 255.0;
        const double red = static_cast<std::uint8_t>(capture.bgra8[pixel + 2]) / 255.0;
        const auto alpha = static_cast<std::uint8_t>(capture.bgra8[pixel + 3]);
        const double luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
        luminanceSum += luminance;
        metrics.brightPixels += luminance > 0.25 ? 1U : 0U;
        metrics.darkPixels += luminance < 0.995 ? 1U : 0U;
        metrics.opaquePixels += alpha == 255U ? 1U : 0U;
    }
    metrics.meanLuminance = luminanceSum / static_cast<double>(capture.width * capture.height);
    return metrics;
}
} // namespace

int main() {
    NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init();
    auto device = aether::metal::adopt(MTL::CreateSystemDefaultDevice());
    if (!device) {
        std::cerr << "No Metal device available\n";
        pool->release();
        return 1;
    }
    if (!resetCaptureArtifacts()) {
        std::cerr << "Unable to reset the Metal golden artifact directory\n";
        pool->release();
        return 1;
    }

    auto contextResult = aether::metal::FrameContext::create(device.get(), 0);
    if (!contextResult) {
        std::cerr << contextResult.error().describe() << '\n';
        pool->release();
        return 1;
    }
    auto& context = **contextResult;
    const auto first = context.allocateUpload(32, 256);
    const auto second = context.allocateUpload(32, 256);
    if (!first || !second || first->offset != 0 || second->offset != 256 || !first->cpuAddress) {
        std::cerr << "Upload ring alignment failed\n";
        pool->release();
        return 1;
    }
    if (context.allocateReadback(context.readbackCapacity() + 1).has_value()) {
        std::cerr << "Readback ring accepted an oversized allocation\n";
        pool->release();
        return 1;
    }

    bool retired = false;
    context.deferUntilReusable([&] { retired = true; });
    context.beginFrame();
    if (!retired || context.allocateUpload(16)->offset != 0) {
        std::cerr << "Frame reset/deferred cleanup failed\n";
        pool->release();
        return 1;
    }

    auto renderer = aether::metal::Renderer::create(device.get(), AETHER_TEST_SHADER_LIBRARY);
    if (!renderer) {
        std::cerr << renderer.error().describe() << '\n';
        pool->release();
        return 1;
    }
    (*renderer)->setExposureStops(100.0F);
    if ((*renderer)->exposureStops() != 16.0F) {
        std::cerr << "Renderer exposure upper clamp failed\n";
        pool->release();
        return 1;
    }
    (*renderer)->setExposureStops(-100.0F);
    if ((*renderer)->exposureStops() != -16.0F) {
        std::cerr << "Renderer exposure lower clamp failed\n";
        pool->release();
        return 1;
    }
    (*renderer)->setExposureStops(0.0F);
    aether::metal::CameraSnapshot restoredCamera;
    restoredCamera.position = {1.0F, 2.0F, 3.0F};
    restoredCamera.yaw = 0.2F;
    restoredCamera.pitch = -0.1F;
    restoredCamera.verticalFieldOfViewRadians = 0.9F;
    auto invalidCamera = restoredCamera;
    invalidCamera.verticalFieldOfViewRadians = 4.0F;
    if (!(*renderer)->setCameraSnapshot(restoredCamera) ||
        (*renderer)->setCameraSnapshot(invalidCamera)) {
        std::cerr << "Renderer camera snapshot validation failed\n";
        pool->release();
        return 1;
    }
    const auto cameraSnapshot = (*renderer)->cameraSnapshot();
    if (simd_distance(cameraSnapshot.position, restoredCamera.position) > 1.0e-5F ||
        std::abs(cameraSnapshot.yaw - restoredCamera.yaw) > 1.0e-5F ||
        std::abs(cameraSnapshot.pitch - restoredCamera.pitch) > 1.0e-5F ||
        std::abs(cameraSnapshot.verticalFieldOfViewRadians -
                 restoredCamera.verticalFieldOfViewRadians) > 1.0e-5F) {
        std::cerr << "Renderer camera snapshot did not round-trip\n";
        pool->release();
        return 1;
    }
    restoredCamera = {};
    if (!(*renderer)->setCameraSnapshot(restoredCamera)) {
        std::cerr << "Renderer could not restore the default camera\n";
        pool->release();
        return 1;
    }
    aether::scene::Light pointLight;
    pointLight.type = aether::scene::LightType::point;
    pointLight.position = {0.0F, 2.0F, -3.0F};
    pointLight.range = 8.0F;
    aether::scene::Light spotLight;
    spotLight.type = aether::scene::LightType::spot;
    spotLight.position = {1.0F, 3.0F, 0.0F};
    spotLight.direction = {0.0F, -1.0F, -0.25F};
    if (!(*renderer)->setLights({pointLight, spotLight}) || (*renderer)->setLights({})) {
        std::cerr << "Renderer bounded light API validation failed\n";
        pool->release();
        return 1;
    }
    auto editedLight = (*renderer)->lights().front();
    editedLight.intensity = 3.0F;
    if (!(*renderer)->setLight(1, editedLight) || (*renderer)->setLight(0, editedLight) ||
        !(*renderer)->setLight(1, pointLight)) {
        std::cerr << "Renderer indexed light edit validation failed\n";
        pool->release();
        return 1;
    }
    aether::scene::Light extraLight;
    extraLight.type = aether::scene::LightType::directional;
    auto addedLight = (*renderer)->addLight(extraLight);
    if (!addedLight || *addedLight != 3 || !(*renderer)->removeLight(3) ||
        (*renderer)->removeLight(0)) {
        std::cerr << "Renderer light add/remove lifecycle failed\n";
        pool->release();
        return 1;
    }
    aether::scene::ImageBasedLightingData tinyIbl;
    tinyIbl.irradiance.size = 1;
    tinyIbl.irradiance.linearRgb.assign(6, simd_float3{0.1F, 0.1F, 0.1F});
    tinyIbl.prefilteredSpecular.push_back(tinyIbl.irradiance);
    tinyIbl.brdfLutSize = 1;
    tinyIbl.brdfLut.push_back(simd_float2{1.0F, 0.0F});
    if (!(*renderer)->setImageBasedLighting(tinyIbl, 1.0F) ||
        (*renderer)->setImageBasedLighting(tinyIbl, -1.0F)) {
        std::cerr << "Renderer IBL upload validation failed\n";
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_GLTF); !loaded) {
        std::cerr << loaded.error().describe() << '\n';
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_TEXTURED_GLTF); !loaded) {
        std::cerr << loaded.error().describe() << '\n';
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_INSTANCED_GLTF); !loaded) {
        std::cerr << "Renderer could not upload shared instanced glTF geometry: "
                  << loaded.error().describe() << '\n';
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_ANIMATED_GLTF);
        !loaded || (*renderer)->animationClipCount() != 1 ||
        !(*renderer)->selectAnimation(0, true)) {
        std::cerr << "Renderer could not upload and select glTF animation\n";
        pool->release();
        return 1;
    }
    if (!(*renderer)->setAnimationPlayback(0U, 0.25F, false, false) ||
        (*renderer)->setAnimationPlayback(1U, 0.0F, true, true) ||
        (*renderer)->setAnimationPlayback(std::nullopt, -1.0F, true, true)) {
        std::cerr << "Serialized animation playback validation failed\n";
        pool->release();
        return 1;
    }
    if (!(*renderer)->setAnimationPlayback(0U, 0.0F, true, true)) {
        std::cerr << "Renderer could not restore default animation playback\n";
        pool->release();
        return 1;
    }
    (*renderer)->seekAnimation(0.5F);
    (*renderer)->setAnimationPlaying(false);
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_SKINNED_GLTF); !loaded) {
        std::cerr << "Renderer could not upload skinned glTF: " << loaded.error().describe()
                  << '\n';
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_MORPHED_GLTF); !loaded) {
        std::cerr << "Renderer could not upload morphed glTF: " << loaded.error().describe()
                  << '\n';
        pool->release();
        return 1;
    }
    auto testView = aether::metal::adopt(
        MTK::View::alloc()->init(CGRectMake(0.0, 0.0, 320.0, 180.0), device.get()));
    if (!testView) {
        std::cerr << "Unable to create offscreen Metal renderer test view\n";
        pool->release();
        return 1;
    }
    testView->setColorPixelFormat(MTL::PixelFormatBGRA8Unorm_sRGB);
    testView->setDepthStencilPixelFormat(MTL::PixelFormatDepth32Float);
    testView->setFramebufferOnly(false);
    testView->setDrawableSize(CGSizeMake(320.0, 180.0));
    (*renderer)->draw(testView.get());
    for (std::uint32_t attempt = 0; attempt < 100 && (*renderer)->statistics().completedFrames == 0;
         ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if ((*renderer)->statistics().completedFrames == 0) {
        std::cerr << "Renderer did not complete the offscreen shadow/post-processing frame\n";
        pool->release();
        return 1;
    }
    (*renderer)->requestFrameCapture();
    (*renderer)->draw(testView.get());
    for (std::uint32_t attempt = 0; attempt < 100 && (*renderer)->statistics().completedFrames < 2;
         ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if ((*renderer)->statistics().completedFrames < 2) {
        std::cerr << "Renderer did not complete the temporal-history frame\n";
        pool->release();
        return 1;
    }
    auto frameCapture = (*renderer)->consumeFrameCapture();
    if (!frameCapture || frameCapture->width != 320 || frameCapture->height != 180 ||
        frameCapture->bgra8.size() != 320U * 180U * 4U) {
        std::cerr << "Renderer frame capture dimensions are invalid\n";
        pool->release();
        return 1;
    }
    const auto pbrMetrics = measureCapture(*frameCapture);
    if (!writeCaptureArtifact(*frameCapture, "pbr-final") || pbrMetrics.meanLuminance < 0.17 ||
        pbrMetrics.meanLuminance > 0.20 || pbrMetrics.brightPixels < 2'500 ||
        pbrMetrics.brightPixels > 4'500 || pbrMetrics.opaquePixels != 320U * 180U) {
        std::cerr << "PBR golden thresholds failed: mean=" << pbrMetrics.meanLuminance
                  << " bright=" << pbrMetrics.brightPixels << " opaque=" << pbrMetrics.opaquePixels
                  << '\n';
        pool->release();
        return 1;
    }
    const auto pickedMesh = (*renderer)->pickMesh(160, 90);
    const auto pickedBackground = (*renderer)->pickMesh(4, 4);
    const auto entityNames = (*renderer)->meshEntityNames();
    if (!pickedMesh || *pickedMesh != 1 || !pickedBackground || *pickedBackground != 0 ||
        entityNames.size() != 1 || entityNames.front().empty()) {
        std::cerr << "Depth-tested mesh entity-ID picking disagrees with the golden fixture\n";
        pool->release();
        return 1;
    }
    if (!(*renderer)->setSelectedMeshEntity(1)) {
        std::cerr << "Renderer rejected a valid gizmo selection\n";
        pool->release();
        return 1;
    }
    (*renderer)->draw(testView.get());
    for (std::uint32_t attempt = 0; attempt < 100 && (*renderer)->statistics().completedFrames < 3;
         ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    const auto gizmoAxis = (*renderer)->pickGizmoAxis(175, 90);
    const auto translated = (*renderer)->translateSelectedMesh(1, 0.1F);
    if ((*renderer)->statistics().completedFrames < 3 || !gizmoAxis || *gizmoAxis != 1 ||
        !translated || !translated->overridden ||
        std::abs(translated->worldTransform.translation.x - 0.1F) > 1.0e-4F ||
        (*renderer)->translateSelectedMesh(0, 0.1F)) {
        std::cerr << "Translation gizmo render/pick/drag contract failed: axis="
                  << (gizmoAxis ? std::to_string(*gizmoAxis) : gizmoAxis.error().describe())
                  << " x=" << (translated ? translated->worldTransform.translation.x : -999.0F)
                  << " frames=" << (*renderer)->statistics().completedFrames << '\n';
        pool->release();
        return 1;
    }
    (*renderer)->draw(testView.get());
    for (std::uint32_t attempt = 0; attempt < 100 && (*renderer)->statistics().completedFrames < 4;
         ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    const auto motion = (*renderer)->sampleMotionVector(166, 90);
    if ((*renderer)->statistics().completedFrames < 4 || !motion || motion->x <= 0.005F ||
        motion->x >= 0.05F || std::abs(motion->y) > 0.01F || motion->w < 0.5F) {
        std::cerr << "Rigid motion-vector fixture did not record the translated entity\n";
        pool->release();
        return 1;
    }
    const auto rotated = (*renderer)->rotateSelectedMeshPixels(2U, 10.0F);
    const auto scaled = (*renderer)->scaleSelectedMeshPixels(1U, 10.0F);
    if (!rotated || std::abs(rotated->worldTransform.rotation.vector.y) < 0.01F || !scaled ||
        scaled->worldTransform.scale.x <= 1.0F || (*renderer)->rotateSelectedMeshPixels(0U, 1.0F) ||
        (*renderer)->scaleSelectedMeshPixels(4U, 1.0F)) {
        std::cerr << "Rotation/scale gizmo mutation contract failed\n";
        pool->release();
        return 1;
    }
    if (!(*renderer)->clearMeshEntityTransform(1)) {
        std::cerr << "Renderer could not reset the gizmo fixture transform\n";
        pool->release();
        return 1;
    }
    auto entitySnapshot = (*renderer)->meshEntitySnapshot(1);
    if (!entitySnapshot) {
        std::cerr << "Renderer did not expose an editable mesh entity snapshot\n";
        pool->release();
        return 1;
    }
    auto editedTransform = entitySnapshot->worldTransform;
    editedTransform.translation.x += 0.25F;
    if (!(*renderer)->setMeshEntityTransform(1, editedTransform)) {
        std::cerr << "Renderer rejected a valid mesh transform override\n";
        pool->release();
        return 1;
    }
    entitySnapshot = (*renderer)->meshEntitySnapshot(1);
    if (!entitySnapshot || !entitySnapshot->overridden ||
        std::abs(entitySnapshot->worldTransform.translation.x - editedTransform.translation.x) >
            1.0e-5F ||
        !(*renderer)->clearMeshEntityTransform(1) ||
        (*renderer)->setMeshEntityTransform(0, editedTransform)) {
        std::cerr << "Mesh transform override lifecycle is inconsistent\n";
        pool->release();
        return 1;
    }
    auto materials = (*renderer)->materialSnapshots();
    if (materials.empty() || materials.front().name.empty()) {
        std::cerr << "Renderer did not expose material snapshots\n";
        pool->release();
        return 1;
    }
    auto editedMaterial = materials.front();
    editedMaterial.metallic = 0.2F;
    editedMaterial.roughness = 0.7F;
    if (!(*renderer)->setMaterialOverride(editedMaterial)) {
        std::cerr << "Renderer rejected valid material factors\n";
        pool->release();
        return 1;
    }
    materials = (*renderer)->materialSnapshots();
    auto invalidMaterial = editedMaterial;
    invalidMaterial.id = 0;
    if (!materials.front().overridden || std::abs(materials.front().metallic - 0.2F) > 1.0e-6F ||
        !(*renderer)->clearMaterialOverride(editedMaterial.id) ||
        (*renderer)->setMaterialOverride(invalidMaterial)) {
        std::cerr << "Material override lifecycle is inconsistent\n";
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_SKINNED_GLTF); !loaded) {
        std::cerr << "Renderer could not reload the skinned motion fixture\n";
        pool->release();
        return 1;
    }
    aether::scene::Light goldenSun;
    goldenSun.type = aether::scene::LightType::directional;
    goldenSun.direction = {-0.4F, -1.0F, -0.6F};
    goldenSun.intensity = 4.0F;
    aether::scene::Light goldenSpot;
    goldenSpot.type = aether::scene::LightType::spot;
    goldenSpot.position = {0.0F, 0.0F, 2.0F};
    goldenSpot.direction = {0.0F, 0.0F, -1.0F};
    goldenSpot.range = 8.0F;
    goldenSpot.innerConeRadians = 0.4F;
    goldenSpot.outerConeRadians = 0.7F;
    if (!(*renderer)->setLights({goldenSun, goldenSpot, pointLight})) {
        std::cerr << "Renderer rejected the isolated shadow-golden lights\n";
        pool->release();
        return 1;
    }
    const auto completedBeforeSkin = (*renderer)->statistics().completedFrames;
    (*renderer)->draw(testView.get());
    for (std::uint32_t attempt = 0;
         attempt < 100 && (*renderer)->statistics().completedFrames <= completedBeforeSkin;
         ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if ((*renderer)->statistics().completedFrames <= completedBeforeSkin) {
        std::cerr << "Previous-pose skin palette frame did not complete\n";
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadGltf(AETHER_TEST_SHADOW_GLTF); !loaded) {
        std::cerr << "Renderer could not load the isolated shadow caster fixture\n";
        pool->release();
        return 1;
    }
    const auto captureShadowDiagnostic =
        [&](std::uint32_t mode, std::uint32_t slice) -> std::optional<aether::metal::FrameCapture> {
        (*renderer)->setShadowDebugMode(mode, slice);
        const auto completedBeforeDiagnostic = (*renderer)->statistics().completedFrames;
        (*renderer)->requestFrameCapture();
        (*renderer)->draw(testView.get());
        for (std::uint32_t attempt = 0;
             attempt < 100 &&
             (*renderer)->statistics().completedFrames <= completedBeforeDiagnostic;
             ++attempt)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if ((*renderer)->statistics().completedFrames <= completedBeforeDiagnostic)
            return std::nullopt;
        auto capture = (*renderer)->consumeFrameCapture();
        if (!capture)
            return std::nullopt;
        return std::move(*capture);
    };
    (*renderer)->setGizmoMode(1U);
    auto directionalCapture = captureShadowDiagnostic(1U, 0U);
    if (!directionalCapture || measureCapture(*directionalCapture).darkPixels < 8U ||
        !writeCaptureArtifact(*directionalCapture, "shadow-directional-cascade-0")) {
        std::cerr << "Directional shadow golden lacks finite caster coverage\n";
        pool->release();
        return 1;
    }
    (*renderer)->setGizmoMode(2U);
    std::optional<aether::metal::FrameCapture> localCapture;
    std::uint32_t populatedLocalSlice = 0;
    std::size_t maximumLocalCoverage = 0;
    for (std::uint32_t slice = 0; slice < 7U; ++slice) {
        auto candidate = captureShadowDiagnostic(2U, slice);
        if (!candidate)
            continue;
        const auto coverage = measureCapture(*candidate).darkPixels;
        if (coverage > maximumLocalCoverage) {
            maximumLocalCoverage = coverage;
            populatedLocalSlice = slice;
            localCapture = std::move(*candidate);
        }
    }
    if (!localCapture || maximumLocalCoverage < 8U ||
        !writeCaptureArtifact(*localCapture, "shadow-local-populated-face")) {
        std::cerr << "Local point-shadow golden lacks finite caster coverage\n";
        pool->release();
        return 1;
    }
    std::ofstream localFace(std::filesystem::path(AETHER_TEST_ARTIFACT_DIR) /
                                "shadow-local-populated-face.txt",
                            std::ios::trunc);
    localFace << populatedLocalSlice << '\n';
    if (!localFace) {
        std::cerr << "Unable to record populated local shadow face\n";
        pool->release();
        return 1;
    }
    (*renderer)->setGizmoMode(0U);
    (*renderer)->setShadowDebugMode(0U, 0U);

    NS::Error* libraryError = nullptr;
    auto library = aether::metal::adopt(device->newLibrary(
        NS::String::string(AETHER_TEST_SHADER_LIBRARY, NS::UTF8StringEncoding), &libraryError));
    if (!library) {
        std::cerr << "Unable to load Gaussian test shader library\n";
        pool->release();
        return 1;
    }
    auto gaussianPipeline =
        aether::metal::GaussianPipeline::create(device.get(), library.get(), 4096);
    auto gaussianAsset = aether::gaussian::PlyLoader::load(AETHER_TEST_PLY);
    if (gaussianAsset) {
        gaussianAsset->sphericalHarmonicDegree = 1;
        gaussianAsset->gaussians[0].restCount = 9;
        gaussianAsset->gaussians[0].rest[1] = 0.25F;
    }
    if (!gaussianPipeline || !gaussianAsset || !(*gaussianPipeline)->load(*gaussianAsset)) {
        std::cerr << "Unable to prepare Gaussian Metal test\n";
        pool->release();
        return 1;
    }
    if (auto loaded = (*renderer)->loadPly(AETHER_TEST_PLY); !loaded) {
        std::cerr << loaded.error().describe() << '\n';
        pool->release();
        return 1;
    }
    auto canonical = aether::gaussian::GaussianCodec::encode(*gaussianAsset);
    aether::hybrid::ProxyMesh proxyFixture;
    proxyFixture.vertices = {
        {{{-2.0F, -2.0F, 2.25F}}, {{0.0F, 0.0F, 1.0F}}, 0.0F, 0xffffffffU},
        {{{2.0F, -2.0F, 2.25F}}, {{0.0F, 0.0F, 1.0F}}, 0.0F, 0xffffffffU},
        {{{2.0F, 2.0F, 2.25F}}, {{0.0F, 0.0F, 1.0F}}, 0.0F, 0xffffffffU},
        {{{-2.0F, 2.0F, 2.25F}}, {{0.0F, 0.0F, 1.0F}}, 0.0F, 0xffffffffU},
    };
    proxyFixture.indices = {0U, 1U, 2U, 0U, 2U, 3U};
    auto canonicalProxy = aether::hybrid::ProxyMeshCodec::encode(proxyFixture);
    const auto packagePath =
        std::filesystem::temp_directory_path() / "aether-metal-renderer-test.aether";
    constexpr std::string_view metadata = "{\"name\":\"Metal fixture\"}";
    aether::package::PackageWriter packageWriter;
    if (!canonical || !canonicalProxy ||
        !packageWriter.addChunk(aether::package::ChunkType::metadata,
                                std::as_bytes(std::span(metadata.data(), metadata.size()))) ||
        !packageWriter.addChunk(aether::package::ChunkType::baseGaussians, *canonical) ||
        !packageWriter.addChunk(aether::package::ChunkType::proxyMesh, *canonicalProxy) ||
        !packageWriter.write(packagePath) || !(*renderer)->loadAether(packagePath)) {
        std::cerr << "Renderer could not load a canonical AETHER Gaussian package\n";
        pool->release();
        return 1;
    }
    const auto proxyStatistics = (*renderer)->proxyMeshStatistics();
    if (proxyStatistics.vertices != 4U || proxyStatistics.triangles != 2U) {
        std::cerr << "Renderer did not retain canonical proxy geometry\n";
        pool->release();
        return 1;
    }
    std::filesystem::remove(packagePath);
    for (std::uint32_t frameIndex = 0; frameIndex < 2; ++frameIndex) {
        const auto completedBeforeGaussian = (*renderer)->statistics().completedFrames;
        if (frameIndex == 1U)
            (*renderer)->requestFrameCapture();
        (*renderer)->draw(testView.get());
        for (std::uint32_t attempt = 0;
             attempt < 100 && (*renderer)->statistics().completedFrames <= completedBeforeGaussian;
             ++attempt)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if ((*renderer)->statistics().completedFrames <= completedBeforeGaussian) {
            std::cerr << "Gaussian temporal composition frame did not complete\n";
            pool->release();
            return 1;
        }
    }
    auto gaussianCapture = (*renderer)->consumeFrameCapture();
    if (!gaussianCapture || !writeCaptureArtifact(*gaussianCapture, "gaussian-composition")) {
        std::cerr << "Gaussian composition golden capture was not produced\n";
        pool->release();
        return 1;
    }
    const std::size_t gaussianCenter =
        (static_cast<std::size_t>(gaussianCapture->height / 2U) * gaussianCapture->width +
         gaussianCapture->width / 2U) *
        4U;
    const auto centerRed = static_cast<std::uint8_t>(gaussianCapture->bgra8[gaussianCenter + 2U]);
    const auto centerAlpha = static_cast<std::uint8_t>(gaussianCapture->bgra8[gaussianCenter + 3U]);
    if (centerRed < 32U || centerAlpha != 255U) {
        std::cerr << "Gaussian composition golden lacks an opaque center contribution: red="
                  << static_cast<unsigned>(centerRed) << '\n';
        pool->release();
        return 1;
    }
    const auto gaussianMotion = (*renderer)->sampleMotionVector(160, 90);
    if (!gaussianMotion || gaussianMotion->w < 0.5F || gaussianMotion->z <= 0.0F ||
        gaussianMotion->z >= 1.0F || std::abs(gaussianMotion->x) > 0.02F ||
        std::abs(gaussianMotion->y) > 0.02F) {
        std::cerr << "Gaussian temporal composition did not emit bounded camera motion and depth\n";
        pool->release();
        return 1;
    }
    for (auto& vertex : proxyFixture.vertices)
        vertex.confidence = 1.0F;
    canonicalProxy = aether::hybrid::ProxyMeshCodec::encode(proxyFixture);
    const auto occlusionPackagePath =
        std::filesystem::temp_directory_path() / "aether-metal-proxy-occlusion-test.aether";
    aether::package::PackageWriter occlusionWriter;
    if (!canonicalProxy ||
        !occlusionWriter.addChunk(aether::package::ChunkType::metadata,
                                  std::as_bytes(std::span(metadata.data(), metadata.size()))) ||
        !occlusionWriter.addChunk(aether::package::ChunkType::baseGaussians, *canonical) ||
        !occlusionWriter.addChunk(aether::package::ChunkType::proxyMesh, *canonicalProxy) ||
        !occlusionWriter.write(occlusionPackagePath) ||
        !(*renderer)->loadAether(occlusionPackagePath)) {
        std::cerr << "Renderer could not load the proxy occlusion fixture\n";
        pool->release();
        return 1;
    }
    std::filesystem::remove(occlusionPackagePath);
    for (std::uint32_t frameIndex = 0; frameIndex < 2U; ++frameIndex) {
        const auto completedBeforeProxy = (*renderer)->statistics().completedFrames;
        if (frameIndex == 1U)
            (*renderer)->requestFrameCapture();
        (*renderer)->draw(testView.get());
        for (std::uint32_t attempt = 0;
             attempt < 100 && (*renderer)->statistics().completedFrames <= completedBeforeProxy;
             ++attempt)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if ((*renderer)->statistics().completedFrames <= completedBeforeProxy) {
            std::cerr << "Proxy occlusion frame did not complete\n";
            pool->release();
            return 1;
        }
    }
    auto proxyCapture = (*renderer)->consumeFrameCapture();
    if (!proxyCapture || !writeCaptureArtifact(*proxyCapture, "proxy-occlusion")) {
        std::cerr << "Proxy occlusion golden capture was not produced\n";
        pool->release();
        return 1;
    }
    const std::size_t proxyCenter =
        (static_cast<std::size_t>(proxyCapture->height / 2U) * proxyCapture->width +
         proxyCapture->width / 2U) *
        4U;
    const auto occludedRed = static_cast<std::uint8_t>(proxyCapture->bgra8[proxyCenter + 2U]);
    const auto proxyId = (*renderer)->pickProxy(160U, 90U);
    const auto proxyMotion = (*renderer)->sampleMotionVector(160U, 90U);
    if (occludedRed + 32U >= centerRed || !proxyId || *proxyId != 1U || !proxyMotion ||
        proxyMotion->w < 0.5F || proxyMotion->z <= 0.0F || proxyMotion->z >= 1.0F) {
        std::cerr << "Confidence-aware proxy surface did not occlude the behind-surface Gaussian\n";
        pool->release();
        return 1;
    }
    if (!(*renderer)->attachDynamicGltf(AETHER_TEST_GLTF) ||
        (*renderer)->attachDynamicGltf("/aether/missing-dynamic-mesh.glb") ||
        (*renderer)->proxyMeshStatistics().triangles != 2U ||
        (*renderer)->meshEntityNames().size() != 1U) {
        std::cerr << "Dynamic glTF attachment did not preserve the captured world contract\n";
        pool->release();
        return 1;
    }
    aether::scene::Transform dynamicTransform;
    dynamicTransform.translation = {0.0F, 0.0F, 2.30F};
    if (!(*renderer)->setMeshEntityTransform(1U, dynamicTransform)) {
        std::cerr << "Unable to place the dynamic mesh in front of the proxy\n";
        pool->release();
        return 1;
    }
    auto renderHybridCapture = [&](std::string_view artifact) -> bool {
        const auto completedBeforeHybrid = (*renderer)->statistics().completedFrames;
        (*renderer)->requestFrameCapture();
        (*renderer)->draw(testView.get());
        for (std::uint32_t attempt = 0;
             attempt < 100 && (*renderer)->statistics().completedFrames <= completedBeforeHybrid;
             ++attempt)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if ((*renderer)->statistics().completedFrames <= completedBeforeHybrid)
            return false;
        auto capture = (*renderer)->consumeFrameCapture();
        return capture && writeCaptureArtifact(*capture, artifact);
    };
    if (!renderHybridCapture("hybrid-mesh-front")) {
        std::cerr << "Front-of-proxy dynamic mesh frame did not complete\n";
        pool->release();
        return 1;
    }
    const auto frontMeshId = (*renderer)->pickMesh(160U, 90U);
    dynamicTransform.translation.z = 2.0F;
    if (!frontMeshId || *frontMeshId != 1U ||
        !(*renderer)->setMeshEntityTransform(1U, dynamicTransform) ||
        !renderHybridCapture("hybrid-mesh-behind")) {
        std::cerr << "Dynamic mesh was not selectable in front of the proxy\n";
        pool->release();
        return 1;
    }
    const auto behindMeshId = (*renderer)->pickMesh(160U, 90U);
    if (!behindMeshId || *behindMeshId != 0U) {
        std::cerr << "Proxy reverse-Z depth did not occlude the behind-surface dynamic mesh\n";
        pool->release();
        return 1;
    }
    (*renderer)->detachDynamicGltf();
    if (!(*renderer)->meshEntityNames().empty() ||
        (*renderer)->proxyMeshStatistics().triangles != 2U) {
        std::cerr << "Dynamic mesh detach damaged captured-world state\n";
        pool->release();
        return 1;
    }
    constexpr std::size_t width = 9;
    constexpr std::size_t height = 9;
    auto color = makeTexture(device.get(), MTL::PixelFormatRGBA32Float, width, height);
    auto depth = makeTexture(device.get(), MTL::PixelFormatR32Float, width, height);
    auto ids = makeTexture(device.get(), MTL::PixelFormatR32Uint, width, height);
    auto queue = aether::metal::adopt(device->newCommandQueue());
    MTL::CommandBuffer* commandBuffer = queue ? queue->commandBuffer() : nullptr;
    if (!color || !depth || !ids || !commandBuffer) {
        std::cerr << "Unable to allocate Gaussian Metal test targets\n";
        pool->release();
        return 1;
    }
    AetherGaussianCamera camera{};
    camera.worldToCamera = matrix_identity_float4x4;
    camera.focalCenter = {8.0F, 8.0F, 4.5F, 4.5F};
    camera.depthViewport = {0.01F, 100.0F, static_cast<float>(width), static_cast<float>(height)};
    auto encoded =
        (*gaussianPipeline)->encode(commandBuffer, camera, color.get(), depth.get(), ids.get(), 0);
    if (!encoded) {
        std::cerr << encoded.error().describe() << '\n';
        pool->release();
        return 1;
    }
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError) {
        std::cerr << "Gaussian Metal command buffer failed\n";
        pool->release();
        return 1;
    }
    std::vector<simd_float4> colorPixels(width * height);
    std::vector<float> depthPixels(width * height);
    std::vector<std::uint32_t> idPixels(width * height);
    const auto region = MTL::Region::Make2D(0, 0, width, height);
    color->getBytes(colorPixels.data(), width * sizeof(simd_float4), region, 0);
    depth->getBytes(depthPixels.data(), width * sizeof(float), region, 0);
    ids->getBytes(idPixels.data(), width * sizeof(std::uint32_t), region, 0);
    constexpr std::size_t center = 4 * width + 4;
    const auto gaussianStats = (*gaussianPipeline)->statistics();
    if (colorPixels[center].w < 0.9F || std::abs(depthPixels[center] - 2.0F) > 1.0e-4F ||
        idPixels[center] != 1 || gaussianStats.visibleGaussians != 1 ||
        gaussianStats.tileEntries == 0 || gaussianStats.overflowedEntries != 0) {
        std::cerr << "Gaussian Metal projection/compositing result disagrees with CPU fixture\n";
        pool->release();
        return 1;
    }
    aether::gaussian::ReferenceCamera referenceCamera;
    referenceCamera.width = width;
    referenceCamera.height = height;
    referenceCamera.focalX = 8.0F;
    referenceCamera.focalY = 8.0F;
    referenceCamera.centerX = 4.5F;
    referenceCamera.centerY = 4.5F;
    referenceCamera.nearPlane = 0.01F;
    referenceCamera.farPlane = 100.0F;
    auto reference = aether::gaussian::ReferenceRasterizer::render(*gaussianAsset, referenceCamera);
    if (!reference) {
        std::cerr << reference.error().describe() << '\n';
        pool->release();
        return 1;
    }
    for (std::size_t pixel = 0; pixel < width * height; ++pixel) {
        for (std::size_t channel = 0; channel < 4; ++channel) {
            if (std::abs(colorPixels[pixel][channel] - reference->color[pixel][channel]) >
                2.0e-4F) {
                std::cerr << "Gaussian Metal color differs from the CPU oracle\n";
                pool->release();
                return 1;
            }
        }
        const bool bothInfinite =
            std::isinf(depthPixels[pixel]) && std::isinf(reference->depth[pixel]);
        if ((!bothInfinite && std::abs(depthPixels[pixel] - reference->depth[pixel]) > 1.0e-4F) ||
            idPixels[pixel] != reference->ids[pixel]) {
            std::cerr << "Gaussian Metal depth/ID differs from the CPU oracle\n";
            pool->release();
            return 1;
        }
    }

    camera.debugOptions.x = 2;
    MTL::CommandBuffer* debugCommand = queue->commandBuffer();
    if (!debugCommand ||
        !(*gaussianPipeline)->encode(debugCommand, camera, color.get(), depth.get(), ids.get(), 1)) {
        std::cerr << "Unable to encode Gaussian source-ID debug view\n";
        pool->release();
        return 1;
    }
    debugCommand->commit();
    debugCommand->waitUntilCompleted();
    color->getBytes(colorPixels.data(), width * sizeof(simd_float4), region, 0);
    const simd_float4 debugPixel = colorPixels[center];
    if (debugPixel.w != 1.0F ||
        simd_length(simd_float3{debugPixel.x, debugPixel.y, debugPixel.z}) <= 0.0F) {
        std::cerr << "Gaussian source-ID debug view did not produce a visible hash color\n";
        pool->release();
        return 1;
    }
    for (const std::uint32_t debugMode : {5U, 6U}) {
        camera.debugOptions.x = debugMode;
        MTL::CommandBuffer* visualizationCommand = queue->commandBuffer();
        if (!visualizationCommand ||
            !(*gaussianPipeline)
                 ->encode(visualizationCommand, camera, color.get(), depth.get(), ids.get(), 2)) {
            std::cerr << "Unable to encode Gaussian representation visualization\n";
            pool->release();
            return 1;
        }
        visualizationCommand->commit();
        visualizationCommand->waitUntilCompleted();
        color->getBytes(colorPixels.data(), width * sizeof(simd_float4), region, 0);
        const simd_float4 visualization = colorPixels[center];
        const bool expected = debugMode == 5U ? visualization.y > 0.8F : visualization.z > 0.4F;
        if (visualization.w != 1.0F || !expected) {
            std::cerr << "Gaussian SH-band/sort-rank visualization is incorrect\n";
            pool->release();
            return 1;
        }
    }
    camera.debugOptions.x = 0;

    auto multiBlockAsset = *gaussianAsset;
    multiBlockAsset.gaussians.assign(513, gaussianAsset->gaussians.front());
    for (std::size_t index = 0; index < multiBlockAsset.gaussians.size(); ++index) {
        auto& gaussian = multiBlockAsset.gaussians[index];
        gaussian.position[2] = 1.5F + static_cast<float>((index * 97U) % 513U) / 1026.0F;
        gaussian.opacityLogit = -4.0F;
        gaussian.dc[0] = static_cast<float>(index % 7U) * 0.15F;
    }
    auto multiBlockPipeline =
        aether::metal::GaussianPipeline::create(device.get(), library.get(), 4096);
    auto multiBlockColor = makeTexture(device.get(), MTL::PixelFormatRGBA32Float, width, height);
    auto multiBlockDepth = makeTexture(device.get(), MTL::PixelFormatR32Float, width, height);
    auto multiBlockIds = makeTexture(device.get(), MTL::PixelFormatR32Uint, width, height);
    MTL::CommandBuffer* multiBlockCommand = queue->commandBuffer();
    if (!multiBlockPipeline || !(*multiBlockPipeline)->load(multiBlockAsset) ||
        !multiBlockCommand ||
        !(*multiBlockPipeline)
             ->encode(multiBlockCommand, camera, multiBlockColor.get(), multiBlockDepth.get(),
                      multiBlockIds.get())) {
        std::cerr << "Unable to encode multi-block Gaussian scan test\n";
        pool->release();
        return 1;
    }
    multiBlockCommand->commit();
    multiBlockCommand->waitUntilCompleted();
    std::vector<simd_float4> multiBlockPixels(width * height);
    multiBlockColor->getBytes(multiBlockPixels.data(), width * sizeof(simd_float4), region, 0);
    auto multiBlockReference =
        aether::gaussian::ReferenceRasterizer::render(multiBlockAsset, referenceCamera);
    const auto multiBlockStats = (*multiBlockPipeline)->statistics();
    bool centerMatches = multiBlockReference.has_value();
    if (multiBlockReference) {
        for (std::size_t channel = 0; channel < 4; ++channel) {
            centerMatches =
                centerMatches && std::abs(multiBlockPixels[center][channel] -
                                          multiBlockReference->color[center][channel]) < 2.0e-4F;
        }
    }
    if (!multiBlockReference || multiBlockStats.visibleGaussians != 513 ||
        multiBlockStats.tileEntries != 513 || multiBlockStats.overflowedEntries != 0 ||
        !centerMatches) {
        std::cerr << "Parallel Gaussian scan/radix disagrees across 256-item blocks\n";
        pool->release();
        return 1;
    }

    auto boundedPipeline = aether::metal::GaussianPipeline::create(device.get(), library.get(), 1);
    auto boundedColor = makeTexture(device.get(), MTL::PixelFormatRGBA32Float, 32, 32);
    auto boundedDepth = makeTexture(device.get(), MTL::PixelFormatR32Float, 32, 32);
    auto boundedIds = makeTexture(device.get(), MTL::PixelFormatR32Uint, 32, 32);
    MTL::CommandBuffer* boundedCommand = queue->commandBuffer();
    AetherGaussianCamera boundedCamera{};
    boundedCamera.worldToCamera = matrix_identity_float4x4;
    boundedCamera.focalCenter = {64.0F, 64.0F, 16.0F, 16.0F};
    boundedCamera.depthViewport = {0.01F, 100.0F, 32.0F, 32.0F};
    if (!boundedPipeline || !(*boundedPipeline)->load(*gaussianAsset) || !boundedCommand ||
        !(*boundedPipeline)
             ->encode(boundedCommand, boundedCamera, boundedColor.get(), boundedDepth.get(),
                      boundedIds.get())) {
        std::cerr << "Unable to encode bounded Gaussian tile test\n";
        pool->release();
        return 1;
    }
    boundedCommand->commit();
    boundedCommand->waitUntilCompleted();
    const auto boundedStats = (*boundedPipeline)->statistics();
    if (boundedStats.tileEntries != 1 || boundedStats.overflowedEntries == 0) {
        std::cerr << "Gaussian tile-entry budget did not report bounded overflow\n";
        pool->release();
        return 1;
    }

    // Programmatic GPU frame-capture validation (Phase 1 gate)
    auto* captureManager = MTL::CaptureManager::sharedCaptureManager();
    if (captureManager) {
        auto captureDesc = aether::metal::adopt(MTL::CaptureDescriptor::alloc()->init());
        captureDesc->setCaptureObject(device.get());
        captureDesc->setDestination(MTL::CaptureDestinationGPUTraceDocument);
        
        const std::filesystem::path tracePath = std::filesystem::path(AETHER_TEST_ARTIFACT_DIR) / "RendererValidation.gputrace";
        std::error_code ec;
        std::filesystem::remove_all(tracePath, ec);
        
        NS::String* pathString = NS::String::string(tracePath.c_str(), NS::UTF8StringEncoding);
        NS::URL* traceURL = NS::URL::fileURLWithPath(pathString);
        captureDesc->setOutputURL(traceURL);
        
        NS::Error* captureError = nullptr;
        if (captureManager->supportsDestination(MTL::CaptureDestinationGPUTraceDocument)) {
            std::cout << "Capturing API-validation GPU frame to " << tracePath << "...\n";
            if (captureManager->startCapture(captureDesc.get(), &captureError)) {
                // Submit one offscreen frame to capture all named passes and resources
                testView->setDrawableSize(CGSizeMake(320.0, 180.0));
                (*renderer)->draw(testView.get());
                
                // Wait for the frame to complete
                for (std::uint32_t attempt = 0; attempt < 100 && (*renderer)->statistics().completedFrames < 3; ++attempt) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(10));
                }
                
                captureManager->stopCapture();
                std::cout << "API-validation GPU frame capture completed.\n";
            } else {
                const std::string desc = captureError ? captureError->localizedDescription()->utf8String() : "unknown";
                std::cerr << "MTLCaptureManager startCapture failed: " << desc << "\n";
                pool->release();
                return 1;
            }
        } else {
            std::cout << "GPUTraceDocument capture destination not supported on this configuration.\n";
        }
    }

    std::cout << "AETHER Metal frame-context and Gaussian pipeline tests passed\n";
    pool->release();
    return 0;
}
