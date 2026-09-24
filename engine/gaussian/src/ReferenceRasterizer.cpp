#include <aether/gaussian/ReferenceRasterizer.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <numeric>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace aether::gaussian {
namespace {

struct Projected final {
    std::size_t sourceIndex{};
    float centerX{};
    float centerY{};
    float depth{};
    float inverseA{};
    float inverseB{};
    float inverseC{};
    float radius{};
    float opacity{};
    std::array<float, 3> color{};
};

using Matrix3 = std::array<std::array<float, 3>, 3>;

Matrix3 rotationMatrix(const std::array<float, 4>& quaternion) {
    const float w = quaternion[0];
    const float x = quaternion[1];
    const float y = quaternion[2];
    const float z = quaternion[3];
    return {{{1.0F - 2.0F * (y * y + z * z), 2.0F * (x * y - z * w), 2.0F * (x * z + y * w)},
             {2.0F * (x * y + z * w), 1.0F - 2.0F * (x * x + z * z), 2.0F * (y * z - x * w)},
             {2.0F * (x * z - y * w), 2.0F * (y * z + x * w), 1.0F - 2.0F * (x * x + y * y)}}};
}

Matrix3 covariance(const Gaussian& gaussian) {
    const Matrix3 rotation = rotationMatrix(gaussian.rotation);
    std::array<float, 3> variance{};
    for (std::size_t index = 0; index < 3; ++index) {
        const float scale = std::exp(gaussian.logScale[index]);
        variance[index] = scale * scale;
    }
    Matrix3 result{};
    for (std::size_t row = 0; row < 3; ++row) {
        for (std::size_t column = 0; column < 3; ++column) {
            for (std::size_t axis = 0; axis < 3; ++axis)
                result[row][column] +=
                    rotation[row][axis] * variance[axis] * rotation[column][axis];
        }
    }
    return result;
}

Matrix3 cameraCovariance(const Matrix3& world, const std::array<float, 16>& transform) {
    Matrix3 intermediate{};
    Matrix3 result{};
    for (std::size_t row = 0; row < 3; ++row) {
        for (std::size_t column = 0; column < 3; ++column) {
            for (std::size_t axis = 0; axis < 3; ++axis)
                intermediate[row][column] += transform[row * 4 + axis] * world[axis][column];
        }
    }
    for (std::size_t row = 0; row < 3; ++row) {
        for (std::size_t column = 0; column < 3; ++column) {
            for (std::size_t axis = 0; axis < 3; ++axis)
                result[row][column] += intermediate[row][axis] * transform[column * 4 + axis];
        }
    }
    return result;
}

std::array<float, 3> transformPoint(const std::array<float, 3>& point,
                                    const std::array<float, 16>& transform) {
    return {
        transform[0] * point[0] + transform[1] * point[1] + transform[2] * point[2] + transform[3],
        transform[4] * point[0] + transform[5] * point[1] + transform[6] * point[2] + transform[7],
        transform[8] * point[0] + transform[9] * point[1] + transform[10] * point[2] +
            transform[11]};
}

float sigmoid(float value) {
    return 1.0F / (1.0F + std::exp(-std::clamp(value, -30.0F, 30.0F)));
}

std::array<float, 3> sphericalHarmonics(const Gaussian& gaussian,
                                        const std::array<float, 3>& cameraPosition) {
    std::array<float, 3> direction{gaussian.position[0] - cameraPosition[0],
                                   gaussian.position[1] - cameraPosition[1],
                                   gaussian.position[2] - cameraPosition[2]};
    const float lengthSquared =
        direction[0] * direction[0] + direction[1] * direction[1] + direction[2] * direction[2];
    if (lengthSquared > 1.0e-20F) {
        const float inverseLength = 1.0F / std::sqrt(lengthSquared);
        for (float& value : direction)
            value *= inverseLength;
    }
    auto coefficient = [&](std::size_t index, std::size_t channel) {
        return index == 0 ? gaussian.dc[channel] : gaussian.rest[channel * 15 + (index - 1)];
    };
    std::array<float, 3> result{};
    auto add = [&](std::size_t index, float basis) {
        for (std::size_t channel = 0; channel < 3; ++channel)
            result[channel] += basis * coefficient(index, channel);
    };
    constexpr float c0 = 0.28209479177387814F;
    constexpr float c1 = 0.4886025119029199F;
    add(0, c0);
    if (gaussian.restCount >= 9) {
        const float x = direction[0];
        const float y = direction[1];
        const float z = direction[2];
        add(1, -c1 * y);
        add(2, c1 * z);
        add(3, -c1 * x);
        if (gaussian.restCount >= 24) {
            constexpr std::array c2{1.0925484305920792F, -1.0925484305920792F, 0.31539156525252005F,
                                    -1.0925484305920792F, 0.5462742152960396F};
            const float xx = x * x;
            const float yy = y * y;
            const float zz = z * z;
            add(4, c2[0] * x * y);
            add(5, c2[1] * y * z);
            add(6, c2[2] * (2.0F * zz - xx - yy));
            add(7, c2[3] * x * z);
            add(8, c2[4] * (xx - yy));
            if (gaussian.restCount >= 45) {
                constexpr std::array c3{-0.5900435899266435F, 2.890611442640554F,
                                        -0.4570457994644658F, 0.3731763325901154F,
                                        -0.4570457994644658F, 1.445305721320277F,
                                        -0.5900435899266435F};
                add(9, c3[0] * y * (3.0F * xx - yy));
                add(10, c3[1] * x * y * z);
                add(11, c3[2] * y * (4.0F * zz - xx - yy));
                add(12, c3[3] * z * (2.0F * zz - 3.0F * xx - 3.0F * yy));
                add(13, c3[4] * x * (4.0F * zz - xx - yy));
                add(14, c3[5] * z * (xx - yy));
                add(15, c3[6] * x * (xx - 3.0F * yy));
            }
        }
    }
    for (float& channel : result)
        channel = std::max(0.0F, channel + 0.5F);
    return result;
}

Result<Projected> project(const Gaussian& gaussian, std::size_t sourceIndex,
                          const ReferenceCamera& camera) {
    const auto point = transformPoint(gaussian.position, camera.worldToCamera);
    if (point[2] < camera.nearPlane || point[2] > camera.farPlane)
        return fail(ErrorCode::notFound, "Gaussian is outside the camera depth range");

    Projected result;
    result.sourceIndex = sourceIndex;
    result.depth = point[2];
    result.centerX = camera.focalX * point[0] / point[2] + camera.centerX;
    result.centerY = camera.focalY * point[1] / point[2] + camera.centerY;

    const Matrix3 cov = cameraCovariance(covariance(gaussian), camera.worldToCamera);
    const float inverseZ = 1.0F / point[2];
    const std::array<float, 3> jacobianX{camera.focalX * inverseZ, 0.0F,
                                         -camera.focalX * point[0] * inverseZ * inverseZ};
    const std::array<float, 3> jacobianY{0.0F, camera.focalY * inverseZ,
                                         -camera.focalY * point[1] * inverseZ * inverseZ};
    auto quadratic = [&](const std::array<float, 3>& lhs, const std::array<float, 3>& rhs) {
        float value = 0.0F;
        for (std::size_t row = 0; row < 3; ++row)
            for (std::size_t column = 0; column < 3; ++column)
                value += lhs[row] * cov[row][column] * rhs[column];
        return value;
    };
    const float a = quadratic(jacobianX, jacobianX) + 0.3F;
    const float b = quadratic(jacobianX, jacobianY);
    const float c = quadratic(jacobianY, jacobianY) + 0.3F;
    const float determinant = a * c - b * b;
    if (!std::isfinite(determinant) || determinant <= 1.0e-12F)
        return fail(ErrorCode::corruptData, "Gaussian projects to a singular covariance");
    result.inverseA = c / determinant;
    result.inverseB = -b / determinant;
    result.inverseC = a / determinant;
    const float discriminant = std::sqrt(std::max(0.0F, (a - c) * (a - c) + 4.0F * b * b));
    const float maximumEigenvalue = 0.5F * (a + c + discriminant);
    result.radius = 3.0F * std::sqrt(maximumEigenvalue);
    if (!std::isfinite(result.radius) || result.radius > 1.0e6F)
        return fail(ErrorCode::resourceExhausted, "Gaussian projected radius is unsafe");
    result.opacity = sigmoid(gaussian.opacityLogit);
    result.color = sphericalHarmonics(gaussian, camera.cameraWorldPosition);
    return result;
}

} // namespace

Result<ReferenceImage> ReferenceRasterizer::render(const GaussianAsset& asset,
                                                   const ReferenceCamera& camera,
                                                   std::array<float, 3> background) {
    constexpr std::size_t maximumDimension = 16'384;
    constexpr std::size_t maximumPixels = 268'435'456;
    if (camera.width == 0 || camera.height == 0 || camera.width > maximumDimension ||
        camera.height > maximumDimension || camera.width > maximumPixels / camera.height ||
        !std::isfinite(camera.focalX) || !std::isfinite(camera.focalY) || camera.focalX <= 0.0F ||
        camera.focalY <= 0.0F || camera.nearPlane <= 0.0F || camera.farPlane <= camera.nearPlane) {
        return fail(ErrorCode::invalidArgument, "Reference camera parameters are invalid");
    }
    if (std::ranges::any_of(camera.worldToCamera,
                            [](float value) { return !std::isfinite(value); })) {
        return fail(ErrorCode::invalidArgument, "Reference camera transform is non-finite");
    }
    const std::size_t pixelCount = camera.width * camera.height;
    ReferenceImage image;
    image.width = camera.width;
    image.height = camera.height;
    image.color.resize(pixelCount, {0.0F, 0.0F, 0.0F, 0.0F});
    image.depth.resize(pixelCount, std::numeric_limits<float>::infinity());
    image.ids.resize(pixelCount, 0);
    std::vector<float> dominant(pixelCount, 0.0F);

    std::vector<Projected> projected;
    projected.reserve(asset.gaussians.size());
    for (std::size_t index = 0; index < asset.gaussians.size(); ++index) {
        auto result = project(asset.gaussians[index], index, camera);
        if (result)
            projected.push_back(*result);
        else if (result.error().code != ErrorCode::notFound)
            return std::unexpected(result.error());
    }
    std::ranges::stable_sort(projected, {}, &Projected::depth);

    constexpr std::size_t kRowBandHeight = 16;
    struct BandEntry final {
        const Projected* gaussian{};
        int minimumX{};
        int maximumX{};
        int minimumY{};
        int maximumY{};
    };
    const std::size_t bandCount =
        (camera.height + kRowBandHeight - 1) / kRowBandHeight;
    std::vector<std::vector<BandEntry>> bands(bandCount);
    for (const Projected& gaussian : projected) {
        const int minimumX =
            std::max(0, static_cast<int>(std::floor(gaussian.centerX - gaussian.radius)));
        const int maximumX =
            std::min(static_cast<int>(camera.width) - 1,
                     static_cast<int>(std::ceil(gaussian.centerX + gaussian.radius)));
        const int minimumY =
            std::max(0, static_cast<int>(std::floor(gaussian.centerY - gaussian.radius)));
        const int maximumY =
            std::min(static_cast<int>(camera.height) - 1,
                     static_cast<int>(std::ceil(gaussian.centerY + gaussian.radius)));
        if (minimumX > maximumX || minimumY > maximumY)
            continue;
        const std::size_t firstBand =
            static_cast<std::size_t>(minimumY) / kRowBandHeight;
        const std::size_t lastBand =
            static_cast<std::size_t>(maximumY) / kRowBandHeight;
        for (std::size_t band = firstBand; band <= lastBand; ++band) {
            bands[band].push_back(
                BandEntry{&gaussian, minimumX, maximumX, minimumY, maximumY});
        }
    }

    auto rasterizeBand = [&](std::size_t band) {
        const int bandMinimumY = static_cast<int>(band * kRowBandHeight);
        const int bandMaximumY =
            std::min(static_cast<int>(camera.height) - 1,
                     bandMinimumY + static_cast<int>(kRowBandHeight) - 1);
        for (const BandEntry& entry : bands[band]) {
            const Projected& gaussian = *entry.gaussian;
            const int minimumY = std::max(entry.minimumY, bandMinimumY);
            const int maximumY = std::min(entry.maximumY, bandMaximumY);
            for (int y = minimumY; y <= maximumY; ++y) {
                for (int x = entry.minimumX; x <= entry.maximumX; ++x) {
                    const float dx = (static_cast<float>(x) + 0.5F) - gaussian.centerX;
                    const float dy = (static_cast<float>(y) + 0.5F) - gaussian.centerY;
                    const float distance = gaussian.inverseA * dx * dx +
                                           2.0F * gaussian.inverseB * dx * dy +
                                           gaussian.inverseC * dy * dy;
                    if (distance > 9.0F)
                        continue;
                    const std::size_t pixel =
                        static_cast<std::size_t>(y) * camera.width +
                        static_cast<std::size_t>(x);
                    const float alpha =
                        std::min(0.99F, gaussian.opacity * std::exp(-0.5F * distance));
                    if (alpha < 1.0F / 255.0F || image.color[pixel][3] > 0.999F)
                        continue;
                    const float contribution = (1.0F - image.color[pixel][3]) * alpha;
                    for (std::size_t channel = 0; channel < 3; ++channel)
                        image.color[pixel][channel] += contribution * gaussian.color[channel];
                    image.color[pixel][3] += contribution;
                    if (image.depth[pixel] == std::numeric_limits<float>::infinity())
                        image.depth[pixel] = gaussian.depth;
                    if (contribution > dominant[pixel]) {
                        dominant[pixel] = contribution;
                        image.ids[pixel] =
                            static_cast<std::uint32_t>(gaussian.sourceIndex + 1);
                    }
                }
            }
        }
    };

    const unsigned hardwareThreads = std::max(1U, std::thread::hardware_concurrency());
    unsigned threadBudget = hardwareThreads;
    auto parsePositiveEnvironment = [](const char* name) -> std::optional<unsigned> {
        const char* value = std::getenv(name);
        if (!value || !*value)
            return std::nullopt;
        unsigned parsed{};
        const char* end = value + std::char_traits<char>::length(value);
        const auto result = std::from_chars(value, end, parsed);
        if (result.ec != std::errc{} || result.ptr != end || parsed == 0)
            return std::nullopt;
        return parsed;
    };
    if (const auto explicitThreads = parsePositiveEnvironment("MAVEB_ORACLE_CPU_THREADS")) {
        threadBudget = *explicitThreads;
    } else if (const auto concurrentCases =
                   parsePositiveEnvironment("MAVEB_CASE_WORKERS")) {
        threadBudget = std::max(1U, hardwareThreads / *concurrentCases);
    }
    const std::size_t workerCount =
        std::min<std::size_t>(bandCount, static_cast<std::size_t>(threadBudget));
    // Small oracle images are faster without thread startup. Larger renders fan out by
    // independent horizontal bands. Every pixel still sees Gaussians in the original global
    // stable depth order, so compositing is deterministic and numerically equivalent.
    if (workerCount <= 1 || pixelCount < 65'536) {
        for (std::size_t band = 0; band < bandCount; ++band)
            rasterizeBand(band);
    } else {
        std::atomic<std::size_t> nextBand{0};
        std::vector<std::thread> workers;
        workers.reserve(workerCount);
        for (std::size_t worker = 0; worker < workerCount; ++worker) {
            workers.emplace_back([&] {
                while (true) {
                    const std::size_t band =
                        nextBand.fetch_add(1, std::memory_order_relaxed);
                    if (band >= bandCount)
                        break;
                    rasterizeBand(band);
                }
            });
        }
        for (auto& worker : workers)
            worker.join();
    }

    for (auto& pixel : image.color) {
        for (std::size_t channel = 0; channel < 3; ++channel)
            pixel[channel] += (1.0F - pixel[3]) * std::clamp(background[channel], 0.0F, 1.0F);
    }
    return image;
}

} // namespace aether::gaussian
