#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>
#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <ranges>

namespace aether::world_gaussian {
namespace {

using Matrix3 = std::array<std::array<double, 3>, 3>;

struct Projected final {
    double centerX{};
    double centerY{};
    double inverseA{};
    double inverseB{};
    double inverseC{};
    double radius{};
    double opacity{};
};

[[nodiscard]] bool opacityOnlyInvariant(const gaussian::Gaussian& before,
                                        const gaussian::Gaussian& after) noexcept {
    return before.position == after.position && before.logScale == after.logScale &&
           before.rotation == after.rotation && before.dc == after.dc &&
           before.rest == after.rest && before.restCount == after.restCount;
}

[[nodiscard]] bool validCamera(const gaussian::ReferenceCamera& camera) noexcept {
    constexpr std::size_t maximumDimension = 16'384;
    constexpr std::size_t maximumPixels = 268'435'456;
    if (camera.width == 0 || camera.height == 0 || camera.width > maximumDimension ||
        camera.height > maximumDimension || camera.width > maximumPixels / camera.height ||
        !std::isfinite(camera.focalX) || !std::isfinite(camera.focalY) || camera.focalX <= 0.0F ||
        camera.focalY <= 0.0F || camera.nearPlane <= 0.0F || camera.farPlane <= camera.nearPlane)
        return false;
    return std::ranges::none_of(camera.worldToCamera,
                                [](float value) { return !std::isfinite(value); });
}

[[nodiscard]] std::array<double, 3>
transformPoint(const std::array<float, 3>& point, const std::array<float, 16>& transform) noexcept {
    return {
        transform[0] * point[0] + transform[1] * point[1] + transform[2] * point[2] + transform[3],
        transform[4] * point[0] + transform[5] * point[1] + transform[6] * point[2] + transform[7],
        transform[8] * point[0] + transform[9] * point[1] + transform[10] * point[2] +
            transform[11],
    };
}

[[nodiscard]] Matrix3 rotationMatrix(const std::array<float, 4>& q) noexcept {
    const double w = q[0];
    const double x = q[1];
    const double y = q[2];
    const double z = q[3];
    return {{
        {1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)},
        {2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)},
        {2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)},
    }};
}

[[nodiscard]] Result<Matrix3> covariance(const gaussian::Gaussian& primitive) {
    for (const float value : primitive.logScale)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian image certificate encountered non-finite scale");
    for (const float value : primitive.position)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian image certificate encountered non-finite position");
    for (const float value : primitive.rotation)
        if (!std::isfinite(value))
            return fail(ErrorCode::corruptData,
                        "Gaussian image certificate encountered non-finite rotation");
    if (!std::isfinite(primitive.opacityLogit))
        return fail(ErrorCode::corruptData,
                    "Gaussian image certificate encountered non-finite opacity");

    double norm2{};
    for (const float value : primitive.rotation)
        norm2 += static_cast<double>(value) * value;
    if (std::abs(norm2 - 1.0) > 1.0e-3)
        return fail(ErrorCode::corruptData,
                    "Gaussian image certificate requires normalized rotation");

    const Matrix3 rotation = rotationMatrix(primitive.rotation);
    std::array<double, 3> variance{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double scale = std::exp(static_cast<double>(primitive.logScale[axis]));
        variance[axis] = scale * scale;
        if (!std::isfinite(variance[axis]) || variance[axis] <= 0.0)
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian image certificate scale is numerically unsafe");
    }

    Matrix3 result{};
    for (std::size_t row = 0; row < 3; ++row)
        for (std::size_t column = 0; column < 3; ++column)
            for (std::size_t axis = 0; axis < 3; ++axis)
                result[row][column] +=
                    rotation[row][axis] * variance[axis] * rotation[column][axis];
    return result;
}

[[nodiscard]] Matrix3 cameraCovariance(const Matrix3& world,
                                       const std::array<float, 16>& transform) noexcept {
    Matrix3 intermediate{};
    Matrix3 result{};
    for (std::size_t row = 0; row < 3; ++row)
        for (std::size_t column = 0; column < 3; ++column)
            for (std::size_t axis = 0; axis < 3; ++axis)
                intermediate[row][column] += transform[row * 4 + axis] * world[axis][column];
    for (std::size_t row = 0; row < 3; ++row)
        for (std::size_t column = 0; column < 3; ++column)
            for (std::size_t axis = 0; axis < 3; ++axis)
                result[row][column] += intermediate[row][axis] * transform[column * 4 + axis];
    return result;
}

[[nodiscard]] Result<Projected> project(const gaussian::Gaussian& primitive,
                                        const gaussian::ReferenceCamera& camera) {
    const auto point = transformPoint(primitive.position, camera.worldToCamera);
    if (point[2] < camera.nearPlane || point[2] > camera.farPlane)
        return fail(ErrorCode::notFound,
                    "Gaussian is outside the image-certificate camera depth range");

    auto worldCovariance = covariance(primitive);
    if (!worldCovariance)
        return std::unexpected(worldCovariance.error());
    const Matrix3 cov = cameraCovariance(*worldCovariance, camera.worldToCamera);

    const double inverseZ = 1.0 / point[2];
    const std::array<double, 3> jacobianX{camera.focalX * inverseZ, 0.0,
                                          -camera.focalX * point[0] * inverseZ * inverseZ};
    const std::array<double, 3> jacobianY{0.0, camera.focalY * inverseZ,
                                          -camera.focalY * point[1] * inverseZ * inverseZ};

    auto quadratic = [&](const std::array<double, 3>& lhs, const std::array<double, 3>& rhs) {
        double value{};
        for (std::size_t row = 0; row < 3; ++row)
            for (std::size_t column = 0; column < 3; ++column)
                value += lhs[row] * cov[row][column] * rhs[column];
        return value;
    };

    const double a = quadratic(jacobianX, jacobianX) + 0.3;
    const double b = quadratic(jacobianX, jacobianY);
    const double c = quadratic(jacobianY, jacobianY) + 0.3;
    const double determinant = a * c - b * b;
    if (!std::isfinite(determinant) || determinant <= 1.0e-12)
        return fail(ErrorCode::corruptData,
                    "Gaussian image certificate projected covariance is singular");

    const double discriminant = std::sqrt(std::max(0.0, (a - c) * (a - c) + 4.0 * b * b));
    const double maximumEigenvalue = 0.5 * (a + c + discriminant);
    const double radius = 3.0 * std::sqrt(maximumEigenvalue);
    if (!std::isfinite(radius) || radius > 1.0e6)
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian image certificate projected radius is unsafe");

    const double opacity =
        1.0 /
        (1.0 + std::exp(-std::clamp(static_cast<double>(primitive.opacityLogit), -30.0, 30.0)));

    return Projected{
        .centerX = camera.focalX * point[0] * inverseZ + camera.centerX,
        .centerY = camera.focalY * point[1] * inverseZ + camera.centerY,
        .inverseA = c / determinant,
        .inverseB = -b / determinant,
        .inverseC = a / determinant,
        .radius = radius,
        .opacity = opacity,
    };
}

} // namespace

Result<GaussianOpacityEnvelope>
projectGaussianOpacityEnvelope(const gaussian::GaussianAsset& changed,
                               const gaussian::ReferenceCamera& camera) {
    if (!validCamera(camera))
        return fail(ErrorCode::invalidArgument,
                    "Gaussian image certificate camera parameters are invalid");

    const std::size_t pixelCount = camera.width * camera.height;
    std::vector<double> transmittance(pixelCount, 1.0);

    for (const gaussian::Gaussian& primitive : changed.gaussians) {
        auto projected = project(primitive, camera);
        if (!projected) {
            if (projected.error().code == ErrorCode::notFound)
                continue;
            return std::unexpected(projected.error());
        }

        const int minimumX =
            std::max(0, static_cast<int>(std::floor(projected->centerX - projected->radius)));
        const int maximumX =
            std::min(static_cast<int>(camera.width) - 1,
                     static_cast<int>(std::ceil(projected->centerX + projected->radius)));
        const int minimumY =
            std::max(0, static_cast<int>(std::floor(projected->centerY - projected->radius)));
        const int maximumY =
            std::min(static_cast<int>(camera.height) - 1,
                     static_cast<int>(std::ceil(projected->centerY + projected->radius)));

        for (int y = minimumY; y <= maximumY; ++y) {
            for (int x = minimumX; x <= maximumX; ++x) {
                const double dx = (static_cast<double>(x) + 0.5) - projected->centerX;
                const double dy = (static_cast<double>(y) + 0.5) - projected->centerY;
                const double distance = projected->inverseA * dx * dx +
                                        2.0 * projected->inverseB * dx * dy +
                                        projected->inverseC * dy * dy;

                auto alpha = effectiveGaussianRendererAlpha(projected->opacity, distance);
                if (!alpha)
                    return std::unexpected(alpha.error());
                if (*alpha == 0.0)
                    continue;

                const std::size_t pixel =
                    static_cast<std::size_t>(y) * camera.width + static_cast<std::size_t>(x);
                transmittance[pixel] *= 1.0 - *alpha;
            }
        }
    }

    GaussianOpacityEnvelope result;
    result.width = camera.width;
    result.height = camera.height;
    result.opacityMass.resize(pixelCount);
    for (std::size_t pixel = 0; pixel < pixelCount; ++pixel)
        result.opacityMass[pixel] = std::clamp(1.0 - transmittance[pixel], 0.0, 1.0);
    return result;
}

Result<GaussianImageRevisionCertificate> certifyGaussianOpacityOnlyImageRevision(
    const gaussian::GaussianAsset& beforeChanged, const gaussian::GaussianAsset& afterChanged,
    const gaussian::ReferenceCamera& camera, double colorUpperBound) {
    if (!validCamera(camera))
        return fail(ErrorCode::invalidArgument,
                    "Gaussian opacity-delta certificate camera parameters are invalid");
    if (!std::isfinite(colorUpperBound) || colorUpperBound < 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian opacity-delta color upper bound must be finite and non-negative");
    if (beforeChanged.sphericalHarmonicDegree != afterChanged.sphericalHarmonicDegree)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian opacity-delta certificate requires identical SH degree");
    if (beforeChanged.gaussians.size() != afterChanged.gaussians.size())
        return fail(ErrorCode::invalidArgument,
                    "Gaussian opacity-delta certificate requires paired primitive counts");

    const std::size_t pixelCount = camera.width * camera.height;
    std::vector<double> alphaVariation(pixelCount, 0.0);

    for (std::size_t index = 0; index < beforeChanged.gaussians.size(); ++index) {
        const gaussian::Gaussian& beforePrimitive = beforeChanged.gaussians[index];
        const gaussian::Gaussian& afterPrimitive = afterChanged.gaussians[index];
        if (!opacityOnlyInvariant(beforePrimitive, afterPrimitive))
            return fail(ErrorCode::invalidArgument,
                        "Gaussian opacity-delta certificate requires opacity-only paired changes");

        auto beforeProjected = project(beforePrimitive, camera);
        auto afterProjected = project(afterPrimitive, camera);
        if (!beforeProjected || !afterProjected) {
            const bool beforeOutside =
                !beforeProjected && beforeProjected.error().code == ErrorCode::notFound;
            const bool afterOutside =
                !afterProjected && afterProjected.error().code == ErrorCode::notFound;
            if (beforeOutside && afterOutside)
                continue;
            if (!beforeProjected && !beforeOutside)
                return std::unexpected(beforeProjected.error());
            if (!afterProjected && !afterOutside)
                return std::unexpected(afterProjected.error());
            return fail(ErrorCode::corruptData,
                        "Opacity-only Gaussian changed camera visibility unexpectedly");
        }

        const double minimumCenterX = std::min(beforeProjected->centerX, afterProjected->centerX);
        const double maximumCenterX = std::max(beforeProjected->centerX, afterProjected->centerX);
        const double minimumCenterY = std::min(beforeProjected->centerY, afterProjected->centerY);
        const double maximumCenterY = std::max(beforeProjected->centerY, afterProjected->centerY);
        const double maximumRadius = std::max(beforeProjected->radius, afterProjected->radius);
        const int minimumX =
            std::max(0, static_cast<int>(std::floor(minimumCenterX - maximumRadius)));
        const int maximumX = std::min(
            static_cast<int>(camera.width) - 1,
            static_cast<int>(std::ceil(maximumCenterX + maximumRadius)));
        const int minimumY =
            std::max(0, static_cast<int>(std::floor(minimumCenterY - maximumRadius)));
        const int maximumY = std::min(
            static_cast<int>(camera.height) - 1,
            static_cast<int>(std::ceil(maximumCenterY + maximumRadius)));

        for (int y = minimumY; y <= maximumY; ++y) {
            for (int x = minimumX; x <= maximumX; ++x) {
                const double beforeDx = (static_cast<double>(x) + 0.5) - beforeProjected->centerX;
                const double beforeDy = (static_cast<double>(y) + 0.5) - beforeProjected->centerY;
                const double afterDx = (static_cast<double>(x) + 0.5) - afterProjected->centerX;
                const double afterDy = (static_cast<double>(y) + 0.5) - afterProjected->centerY;
                const double beforeDistance =
                    beforeProjected->inverseA * beforeDx * beforeDx +
                    2.0 * beforeProjected->inverseB * beforeDx * beforeDy +
                    beforeProjected->inverseC * beforeDy * beforeDy;
                const double afterDistance = afterProjected->inverseA * afterDx * afterDx +
                                             2.0 * afterProjected->inverseB * afterDx * afterDy +
                                             afterProjected->inverseC * afterDy * afterDy;

                auto beforeAlpha =
                    effectiveGaussianRendererAlpha(beforeProjected->opacity, beforeDistance);
                if (!beforeAlpha)
                    return std::unexpected(beforeAlpha.error());
                auto afterAlpha =
                    effectiveGaussianRendererAlpha(afterProjected->opacity, afterDistance);
                if (!afterAlpha)
                    return std::unexpected(afterAlpha.error());

                const double delta = std::abs(*beforeAlpha - *afterAlpha);
                if (delta == 0.0)
                    continue;
                const std::size_t pixel =
                    static_cast<std::size_t>(y) * camera.width + static_cast<std::size_t>(x);
                alphaVariation[pixel] += delta;
                if (!std::isfinite(alphaVariation[pixel]))
                    return fail(ErrorCode::resourceExhausted,
                                "Gaussian opacity-delta alpha variation overflow");
            }
        }
    }

    // ReferenceRasterizer early-terminates a pixel after accumulated alpha exceeds
    // 0.999. Relative to the corresponding full alpha compositor, each endpoint
    // can therefore omit at most 0.001 of transmittance. The two-sided difference
    // costs at most 0.002 * colorUpperBound. We add that allowance only where a
    // changed alpha is actually admitted, preserving exact zero outside support.
    constexpr double kTwoSidedEarlyTerminationTransmittance = 0.002;

    GaussianImageRevisionCertificate result;
    result.width = camera.width;
    result.height = camera.height;
    result.rgbLInfBounds.resize(pixelCount, 0.0);
    for (std::size_t pixel = 0; pixel < pixelCount; ++pixel) {
        if (alphaVariation[pixel] == 0.0)
            continue;
        const double normalized =
            std::min(1.0, alphaVariation[pixel] + kTwoSidedEarlyTerminationTransmittance);
        const double bound = colorUpperBound * normalized;
        if (!std::isfinite(bound))
            return fail(ErrorCode::resourceExhausted, "Gaussian opacity-delta RGB bound overflow");
        result.rgbLInfBounds[pixel] = bound;
        result.maximumRgbLInfBound = std::max(result.maximumRgbLInfBound, bound);
    }
    return result;
}

Result<GaussianImageRevisionCertificate>
certifyGaussianImageRevision(const gaussian::GaussianAsset& beforeChanged,
                             const gaussian::GaussianAsset& afterChanged,
                             const gaussian::ReferenceCamera& camera, double colorUpperBound) {
    if (!std::isfinite(colorUpperBound) || colorUpperBound < 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian image certificate color upper bound must be finite and non-negative");

    auto before = projectGaussianOpacityEnvelope(beforeChanged, camera);
    if (!before)
        return std::unexpected(before.error());
    auto after = projectGaussianOpacityEnvelope(afterChanged, camera);
    if (!after)
        return std::unexpected(after.error());

    GaussianImageRevisionCertificate result;
    result.width = camera.width;
    result.height = camera.height;
    result.rgbLInfBounds.resize(camera.width * camera.height);

    for (std::size_t pixel = 0; pixel < result.rgbLInfBounds.size(); ++pixel) {
        const double termination =
            std::min(1.0, before->opacityMass[pixel] + after->opacityMass[pixel]);
        const double bound = colorUpperBound * termination;
        if (!std::isfinite(bound))
            return fail(ErrorCode::resourceExhausted,
                        "Gaussian image certificate RGB bound overflow");
        result.rgbLInfBounds[pixel] = bound;
        result.maximumRgbLInfBound = std::max(result.maximumRgbLInfBound, bound);
    }
    return result;
}

} // namespace aether::world_gaussian
