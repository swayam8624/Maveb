#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>

#include <cstddef>
#include <vector>

namespace aether::world_gaussian {

struct GaussianOpacityEnvelope final {
    std::size_t width{};
    std::size_t height{};
    std::vector<double> opacityMass;
};

struct GaussianImageRevisionCertificate final {
    std::size_t width{};
    std::size_t height{};
    std::vector<double> rgbLInfBounds;
    double maximumRgbLInfBound{};
};

/// Projects only the supplied Gaussian subset through the same pinhole/covariance
/// equations and effective alpha admission rules as the reference/Metal
/// compositor, then accumulates
///
///   A(p)=1-product_i(1-alpha_i(p))
///
/// per pixel. Accumulation deliberately does not early-terminate at opacity
/// 0.999; including later admitted splats can only enlarge A and is therefore
/// conservative for certification.
[[nodiscard]] Result<GaussianOpacityEnvelope>
projectGaussianOpacityEnvelope(const gaussian::GaussianAsset& changed,
                               const gaussian::ReferenceCamera& camera);

/// Builds a per-pixel RGB L-infinity certificate for replacing beforeChanged
/// by afterChanged while all other layers remain unchanged.
///
/// colorUpperBound must conservatively bound every RGB channel of all
/// potentially visible Gaussian/background content participating at the pixel.
[[nodiscard]] Result<GaussianImageRevisionCertificate>
certifyGaussianImageRevision(const gaussian::GaussianAsset& beforeChanged,
                             const gaussian::GaussianAsset& afterChanged,
                             const gaussian::ReferenceCamera& camera,
                             double colorUpperBound);

} // namespace aether::world_gaussian
