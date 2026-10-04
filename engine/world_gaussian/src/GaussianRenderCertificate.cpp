#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace aether::world_gaussian {
namespace {

[[nodiscard]] Result<double> opacityMass(std::span<const double> alphas) {
    double transmittance = 1.0;
    for (const double alpha : alphas) {
        if (!std::isfinite(alpha) || alpha < 0.0 || alpha > 1.0)
            return fail(ErrorCode::invalidArgument,
                        "Gaussian render certificate alpha must lie in [0,1]");
        transmittance *= 1.0 - alpha;
    }
    const double mass = 1.0 - transmittance;
    if (!std::isfinite(mass))
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian render certificate opacity mass overflow");
    return std::clamp(mass, 0.0, 1.0);
}

[[nodiscard]] bool finiteGaussianColor(const gaussian::Gaussian& primitive) noexcept {
    for (const float value : primitive.dc)
        if (!std::isfinite(value))
            return false;
    for (const float value : primitive.rest)
        if (!std::isfinite(value))
            return false;
    return true;
}

} // namespace

Result<double> effectiveGaussianRendererAlpha(double peakOpacity, double squaredMahalanobis) {
    if (!std::isfinite(peakOpacity) || peakOpacity < 0.0 || peakOpacity > 1.0)
        return fail(ErrorCode::invalidArgument, "Gaussian renderer peak opacity must lie in [0,1]");
    if (!std::isfinite(squaredMahalanobis) || squaredMahalanobis < 0.0)
        return fail(
            ErrorCode::invalidArgument,
            "Gaussian renderer squared Mahalanobis distance must be finite and non-negative");

    if (squaredMahalanobis > 9.0)
        return 0.0;

    const double alpha = std::min(0.99, peakOpacity * std::exp(-0.5 * squaredMahalanobis));
    if (alpha < 1.0 / 255.0)
        return 0.0;
    return alpha;
}

Result<std::array<double, 3>> gaussianRendererColorUpperBound(const gaussian::Gaussian& primitive) {
    if (!finiteGaussianColor(primitive))
        return fail(ErrorCode::corruptData,
                    "Gaussian render certificate encountered non-finite SH coefficient");
    if (primitive.restCount > primitive.rest.size())
        return fail(ErrorCode::corruptData,
                    "Gaussian render certificate restCount exceeds canonical storage");

    constexpr double c0 = 0.28209479177387814;
    constexpr double c1 = 0.4886025119029199;
    constexpr std::array<double, 5> c2{1.0925484305920792, 1.0925484305920792, 0.31539156525252005,
                                       1.0925484305920792, 0.5462742152960396};
    constexpr std::array<double, 7> c3{0.5900435899266435, 2.890611442640554,  0.4570457994644658,
                                       0.3731763325901154, 0.4570457994644658, 1.445305721320277,
                                       0.5900435899266435};

    // Safe absolute maxima for the polynomial factors on the unit sphere.
    constexpr std::array<double, 5> degree2PolynomialBound{1.0, 1.0, 2.0, 1.0, 1.0};
    constexpr std::array<double, 7> degree3PolynomialBound{4.0, 1.0, 4.0, 3.0, 4.0, 1.0, 3.0};

    std::array<double, 3> result{};
    for (std::size_t channel = 0; channel < result.size(); ++channel) {
        double magnitude = c0 * std::abs(static_cast<double>(primitive.dc[channel]));

        if (primitive.restCount >= 9) {
            for (std::size_t index = 0; index < 3; ++index) {
                const double coefficient = primitive.rest[channel * 15 + index];
                magnitude += c1 * std::abs(coefficient);
            }
        }

        if (primitive.restCount >= 24) {
            for (std::size_t index = 0; index < 5; ++index) {
                const double coefficient = primitive.rest[channel * 15 + 3 + index];
                magnitude += c2[index] * degree2PolynomialBound[index] * std::abs(coefficient);
            }
        }

        if (primitive.restCount >= 45) {
            for (std::size_t index = 0; index < 7; ++index) {
                const double coefficient = primitive.rest[channel * 15 + 8 + index];
                magnitude += c3[index] * degree3PolynomialBound[index] * std::abs(coefficient);
            }
        }

        result[channel] = 0.5 + magnitude;
        if (!std::isfinite(result[channel]))
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian render certificate SH upper bound overflow");
    }
    return result;
}

Result<GaussianPixelRevisionCertificate>
certifyGaussianPixelRevision(std::span<const double> beforeEffectiveAlphas,
                             std::span<const double> afterEffectiveAlphas, double colorUpperBound) {
    if (!std::isfinite(colorUpperBound) || colorUpperBound < 0.0)
        return fail(
            ErrorCode::invalidArgument,
            "Gaussian render certificate color upper bound must be finite and non-negative");

    auto beforeMass = opacityMass(beforeEffectiveAlphas);
    if (!beforeMass)
        return std::unexpected(beforeMass.error());
    auto afterMass = opacityMass(afterEffectiveAlphas);
    if (!afterMass)
        return std::unexpected(afterMass.error());

    const double terminationBound = std::min(1.0, *beforeMass + *afterMass);
    const double rgbBound = colorUpperBound * terminationBound;
    if (!std::isfinite(rgbBound))
        return fail(ErrorCode::resourceExhausted, "Gaussian render certificate RGB bound overflow");

    return GaussianPixelRevisionCertificate{
        .beforeEditedOpacityMass = *beforeMass,
        .afterEditedOpacityMass = *afterMass,
        .editedTerminationProbabilityBound = terminationBound,
        .colorUpperBound = colorUpperBound,
        .rgbLInfBound = rgbBound,
    };
}

} // namespace aether::world_gaussian
