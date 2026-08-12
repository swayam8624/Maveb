#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <simd/simd.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace aether::reconstruction {

struct TextureBakeImage final {
    std::size_t width{};
    std::size_t height{};
    /// Linear-sRGB pixels in row-major, top-left origin order.
    std::vector<simd_float3> pixels;
};

enum class TextureCameraModel { pinhole, radial, opencv };

struct TextureBakeCamera final {
    std::string imageName;
    float focalX{};
    float focalY{};
    float principalX{};
    float principalY{};
    TextureCameraModel model{TextureCameraModel::pinhole};
    /// Brown-Conrady coefficients. Radial uses k1/k2/k3; OpenCV additionally uses p1/p2.
    float k1{};
    float k2{};
    float k3{};
    float p1{};
    float p2{};
    /// Camera-to-metric-world transform. Camera axes are +X right, +Y down, +Z forward.
    simd_float4x4 cameraToWorld{matrix_identity_float4x4};
    TextureBakeImage image;
};

struct TextureBakeConfig final {
    std::size_t atlasSize{4096};
    std::size_t gutterPixels{4};
    std::size_t visibilityWidth{512};
    std::size_t visibilityHeight{512};
    std::size_t maximumCamerasPerTriangle{4};
    std::size_t maximumCameras{256};
    std::size_t maximumSourcePixels{256ULL * 1024ULL * 1024ULL};
    std::size_t maximumTriangles{1'000'000};
    std::size_t maximumAtlasPixels{8192ULL * 8192ULL};
    float minimumFacingCosine{0.05F};
    float relativeDepthTolerance{0.0025F};
    float maximumExposureGain{4.0F};
};

struct TextureBakeReport final {
    std::size_t triangles{};
    std::size_t cameras{};
    std::size_t texturedTexels{};
    std::size_t unobservedTexels{};
    std::size_t visibilityRejectedSamples{};
    float coverage{};
    std::vector<float> exposureGains;
};

struct TextureBakeResult final {
    mesh::MeshPrimitive primitive;
    std::size_t atlasWidth{};
    std::size_t atlasHeight{};
    /// Linear-sRGB atlas pixels. Unobserved pixels are neutral gray and alpha is reported
    /// separately.
    std::vector<simd_float3> atlasPixels;
    std::vector<std::uint8_t> coverageMask;
    TextureBakeReport report;
};

class TextureBaker final {
  public:
    /// Input: one finite indexed metric triangle mesh and calibrated metric cameras with decoded
    /// linear-sRGB images. Mesh world coordinates and camera-to-world transforms must share units
    /// and axes. Input mesh instances or deformation are deliberately outside this boundary.
    /// Output: deterministic per-triangle UV geometry, a visibility-tested/exposure-compensated
    /// linear atlas, coverage mask, and quantitative report.
    /// Task: rasterize a mesh depth oracle in each camera, reject occluded or back-facing samples,
    /// blend the strongest views, compensate global exposure, and dilate gutters for safe
    /// filtering. Failure: malformed geometry/calibration, singular transforms, unsafe allocation
    /// requests, insufficient atlas resolution, or a completely unobserved mesh produce structured
    /// errors.
    [[nodiscard]] static Result<TextureBakeResult>
    bake(const mesh::MeshPrimitive& source, const std::vector<TextureBakeCamera>& cameras,
         const TextureBakeConfig& config = {});
};

} // namespace aether::reconstruction
