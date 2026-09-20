#include <aether/world_gaussian/GaussianLocalityCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace aether::world_gaussian {
namespace {

using Matrix3 = std::array<std::array<double, 3>, 3>;

[[nodiscard]] bool finiteBounds(const world::Bounds& bounds) noexcept {
    return std::isfinite(bounds.minimum.x) && std::isfinite(bounds.minimum.y) &&
           std::isfinite(bounds.minimum.z) && std::isfinite(bounds.maximum.x) &&
           std::isfinite(bounds.maximum.y) && std::isfinite(bounds.maximum.z) &&
           bounds.minimum.x < bounds.maximum.x && bounds.minimum.y < bounds.maximum.y &&
           bounds.minimum.z < bounds.maximum.z;
}

[[nodiscard]] double sigmoid(double value) noexcept {
    return 1.0 / (1.0 + std::exp(-std::clamp(value, -30.0, 30.0)));
}

[[nodiscard]] Result<Matrix3> covariance(const gaussian::Gaussian& gaussian) {
    for (const float value : gaussian.position)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian locality certificate encountered non-finite position");
    for (const float value : gaussian.logScale)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian locality certificate encountered non-finite scale");
    for (const float value : gaussian.rotation)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian locality certificate encountered non-finite rotation");
    if (!std::isfinite(gaussian.opacityLogit))
        return fail(ErrorCode::corruptData,
                    "Gaussian locality certificate encountered non-finite opacity");

    double quaternionNormSquared{};
    for (const float value : gaussian.rotation)
        quaternionNormSquared += static_cast<double>(value) * value;
    if (!std::isfinite(quaternionNormSquared) ||
        std::abs(quaternionNormSquared - 1.0) > 1.0e-3) {
        return fail(ErrorCode::corruptData,
                    "Gaussian locality certificate requires normalized rotation");
    }

    const double w = gaussian.rotation[0];
    const double x = gaussian.rotation[1];
    const double y = gaussian.rotation[2];
    const double z = gaussian.rotation[3];
    const Matrix3 rotation{{
        {1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)},
        {2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)},
        {2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)},
    }};

    std::array<double, 3> variance{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double scale = std::exp(static_cast<double>(gaussian.logScale[axis]));
        const double value = scale * scale;
        if (!std::isfinite(value) || value <= std::numeric_limits<double>::min())
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian locality certificate scale is numerically unsafe");
        variance[axis] = value;
    }

    Matrix3 result{};
    for (std::size_t row = 0; row < 3; ++row)
        for (std::size_t column = 0; column < 3; ++column)
            for (std::size_t axis = 0; axis < 3; ++axis)
                result[row][column] +=
                    rotation[row][axis] * variance[axis] * rotation[column][axis];
    return result;
}

[[nodiscard]] Result<std::array<double, 6>>
tailBounds(const gaussian::Gaussian& gaussian, const world::Bounds& volume) {
    auto cov = covariance(gaussian);
    if (!cov)
        return std::unexpected(cov.error());

    const std::array<double, 3> mean{
        gaussian.position[0], gaussian.position[1], gaussian.position[2]};
    const std::array<double, 3> minimum{
        volume.minimum.x, volume.minimum.y, volume.minimum.z};
    const std::array<double, 3> maximum{
        volume.maximum.x, volume.maximum.y, volume.maximum.z};
    const double alpha = sigmoid(gaussian.opacityLogit);

    std::array<double, 6> result{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double variance = (*cov)[axis][axis];
        if (!std::isfinite(variance) || variance <= 0.0)
            return fail(ErrorCode::corruptData,
                        "Gaussian locality certificate covariance is invalid");

        const double toMinimum = mean[axis] - minimum[axis];
        const double toMaximum = maximum[axis] - mean[axis];

        result[axis * 2] =
            toMinimum <= 0.0
                ? alpha
                : alpha * std::exp(-0.5 * toMinimum * toMinimum / variance);
        result[axis * 2 + 1] =
            toMaximum <= 0.0
                ? alpha
                : alpha * std::exp(-0.5 * toMaximum * toMaximum / variance);
    }
    return result;
}

Result<void> accumulate(std::array<double, 6>& faceBounds,
                        std::span<const gaussian::Gaussian> gaussians,
                        const world::Bounds& volume) {
    for (const gaussian::Gaussian& primitive : gaussians) {
        auto tails = tailBounds(primitive, volume);
        if (!tails)
            return std::unexpected(tails.error());
        for (std::size_t face = 0; face < faceBounds.size(); ++face) {
            faceBounds[face] += (*tails)[face];
            if (!std::isfinite(faceBounds[face]))
                return fail(ErrorCode::resourceExhausted,
                            "Gaussian locality certificate bound overflow");
        }
    }
    return {};
}

} // namespace

Result<GaussianTailLocalityCertificate> certifyGaussianDensityLocality(
    std::span<const gaussian::Gaussian> beforeChanged,
    std::span<const gaussian::Gaussian> afterChanged,
    const world::Bounds& editVolume) {
    if (!finiteBounds(editVolume))
        return fail(ErrorCode::invalidArgument,
                    "Gaussian locality certificate edit volume is invalid");

    GaussianTailLocalityCertificate result;
    result.beforeChangedGaussians = beforeChanged.size();
    result.afterChangedGaussians = afterChanged.size();

    if (auto accumulated = accumulate(result.faceDensityBounds, beforeChanged, editVolume);
        !accumulated)
        return std::unexpected(accumulated.error());
    if (auto accumulated = accumulate(result.faceDensityBounds, afterChanged, editVolume);
        !accumulated)
        return std::unexpected(accumulated.error());

    result.outsideDensityBound =
        *std::max_element(result.faceDensityBounds.begin(), result.faceDensityBounds.end());
    return result;
}

} // namespace aether::world_gaussian
