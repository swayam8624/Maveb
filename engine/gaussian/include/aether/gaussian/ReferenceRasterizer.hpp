#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace aether::gaussian {

struct ReferenceCamera final {
    std::size_t width{};
    std::size_t height{};
    float focalX{};
    float focalY{};
    float centerX{};
    float centerY{};
    float nearPlane{0.01F};
    float farPlane{10'000.0F};
    std::array<float, 3> cameraWorldPosition{};
    /// Row-major world-to-camera transform. The camera looks along positive Z for this isolated
    /// reference API; adapters must make renderer coordinate conversion explicit.
    std::array<float, 16> worldToCamera{1.0F, 0.0F, 0.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F,
                                        0.0F, 0.0F, 1.0F, 0.0F, 0.0F, 0.0F, 0.0F, 1.0F};
};

struct ReferenceImage final {
    std::size_t width{};
    std::size_t height{};
    std::vector<std::array<float, 4>> color;
    std::vector<float> depth;
    std::vector<std::uint32_t> ids;
};

class ReferenceRasterizer final {
  public:
    /// Input: canonical Gaussians, calibrated camera, and linear background RGB.
    /// Output: deterministic float RGBA, first-hit depth, and dominant-contributor IDs.
    /// Task: provide a slow correctness oracle for Metal projection and compositing tests.
    [[nodiscard]] static Result<ReferenceImage>
    render(const GaussianAsset& asset, const ReferenceCamera& camera,
           std::array<float, 3> background = {0.0F, 0.0F, 0.0F});
};

} // namespace aether::gaussian
