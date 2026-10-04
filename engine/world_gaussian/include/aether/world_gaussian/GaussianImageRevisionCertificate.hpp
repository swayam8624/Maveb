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
                             const gaussian::ReferenceCamera& camera, double colorUpperBound);

/// Tighter certificate for a revision in which corresponding Gaussian records
/// differ only in opacityLogit. Geometry, source-order depth, and SH color are
/// therefore identical in both states.
///
/// For each pixel the full alpha compositor is Lipschitz in each admitted alpha:
///
///   ||Delta C(p)||_inf <= colorUpperBound * sum_i |alpha_i^a(p)-alpha_i^b(p)|.
///
/// The reference renderer may terminate when accumulated alpha exceeds 0.999.
/// A two-sided 0.002 transmittance allowance is added only on pixels where an
/// opacity delta is present, covering that renderer truncation without turning
/// unaffected pixels into global support.
///
/// This routine fails closed when any paired Gaussian differs in position,
/// covariance/rotation, or SH coefficients. Callers may then use the general
/// opacity-envelope certificate above.
[[nodiscard]] Result<GaussianImageRevisionCertificate> certifyGaussianOpacityOnlyImageRevision(
    const gaussian::GaussianAsset& beforeChanged, const gaussian::GaussianAsset& afterChanged,
    const gaussian::ReferenceCamera& camera, double colorUpperBound);

} // namespace aether::world_gaussian
