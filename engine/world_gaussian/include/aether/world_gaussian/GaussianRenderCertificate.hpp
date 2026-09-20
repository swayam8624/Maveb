#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>

#include <array>
#include <span>

namespace aether::world_gaussian {

struct GaussianPixelRevisionCertificate final {
    double beforeEditedOpacityMass{};
    double afterEditedOpacityMass{};
    double editedTerminationProbabilityBound{};
    double colorUpperBound{};
    double rgbLInfBound{};
};

/// Mirrors the effective per-pixel alpha semantics used by the production
/// Gaussian compositor:
///
///   distance > 9        -> no contribution
///   alpha=min(.99, opacity*exp(-.5*distance))
///   alpha < 1/255       -> no contribution
///
/// peakOpacity is the sigmoid-decoded Gaussian opacity in [0,1].
[[nodiscard]] Result<double>
effectiveGaussianRendererAlpha(double peakOpacity, double squaredMahalanobis);

/// Returns a conservative upper bound on every RGB channel produced by the
/// renderer's spherical-harmonic color evaluation for this Gaussian, over all
/// unit view directions.
///
/// The production shader applies max(SH(direction)+0.5, 0), so the lower bound
/// is zero. This routine deliberately uses simple absolute basis envelopes; it
/// is conservative rather than tight.
[[nodiscard]] Result<std::array<double, 3>>
gaussianRendererColorUpperBound(const gaussian::Gaussian& primitive);

/// Certifies the maximum RGB change caused by replacing one edited Gaussian
/// subset by another at one pixel.
///
/// Assumptions:
/// - every effective alpha is the value actually admitted by the production
///   compositor after distance/clamp/threshold rules;
/// - unchanged layers retain their relative order;
/// - all Gaussian/background RGB values at the pixel lie in
///   [0, colorUpperBound].
///
/// Under front-to-back alpha compositing, inserting an edited set E into an
/// unchanged stack changes the final pixel by at most its termination
/// probability A(E)=1-product_i(1-alpha_i), times the RGB range. Comparing
/// before/after edited sets through the unchanged stack therefore gives
///
///   ||C_before-C_after||_inf
///      <= colorUpperBound * min(1, A_before + A_after).
///
/// This explicitly includes changed transmittance revealing/suppressing
/// unchanged content behind the edited splats.
[[nodiscard]] Result<GaussianPixelRevisionCertificate>
certifyGaussianPixelRevision(std::span<const double> beforeEffectiveAlphas,
                             std::span<const double> afterEffectiveAlphas,
                             double colorUpperBound);

} // namespace aether::world_gaussian
