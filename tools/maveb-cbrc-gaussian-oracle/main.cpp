#include <aether/gaussian/PlyLoader.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>
#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::gaussian::ReferenceCamera;

struct Options final {
    std::string beforePath;
    std::string afterPath;
    std::string changedCsv;
    std::size_t width{320};
    std::size_t height{180};
    float focalX{260.0F};
    float focalY{260.0F};
    float centerX{160.0F};
    float centerY{90.0F};
    float nearPlane{0.01F};
    float farPlane{10'000.0F};
    std::array<float, 3> background{0.0F, 0.0F, 0.0F};
    std::array<float, 3> cameraWorldPosition{0.0F, 0.0F, 0.0F};
    std::array<float, 16> worldToCamera{
        1.0F, 0.0F, 0.0F, 0.0F,
        0.0F, 1.0F, 0.0F, 0.0F,
        0.0F, 0.0F, 1.0F, 0.0F,
        0.0F, 0.0F, 0.0F, 1.0F,
    };
    double epsilon{0.01};
};

[[nodiscard]] std::optional<double> parseDouble(std::string_view text) {
    try {
        std::size_t consumed{};
        const double value = std::stod(std::string(text), &consumed);
        if (consumed != text.size() || !std::isfinite(value))
            return std::nullopt;
        return value;
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] std::optional<std::size_t> parseSize(std::string_view text) {
    try {
        std::size_t consumed{};
        const auto value = std::stoull(std::string(text), &consumed);
        if (consumed != text.size())
            return std::nullopt;
        return static_cast<std::size_t>(value);
    } catch (...) {
        return std::nullopt;
    }
}

template <std::size_t N>
[[nodiscard]] std::optional<std::array<float, N>>
parseFloatCsv(std::string_view csv) {
    std::array<float, N> result{};
    std::size_t start{};
    for (std::size_t index = 0; index < N; ++index) {
        const std::size_t comma = csv.find(',', start);
        const std::size_t end = comma == std::string_view::npos ? csv.size() : comma;
        if (end == start)
            return std::nullopt;
        auto value = parseDouble(csv.substr(start, end - start));
        if (!value)
            return std::nullopt;
        result[index] = static_cast<float>(*value);
        if (index + 1 < N) {
            if (comma == std::string_view::npos)
                return std::nullopt;
            start = comma + 1;
        } else if (comma != std::string_view::npos) {
            return std::nullopt;
        }
    }
    return result;
}

[[nodiscard]] std::optional<Options> parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        const auto requireValue = [&](std::string_view name)
            -> std::optional<std::string_view> {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << name << '\n';
                return std::nullopt;
            }
            return std::string_view(argv[++i]);
        };

        if (arg == "--before") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.beforePath = *value;
        } else if (arg == "--after") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.afterPath = *value;
        } else if (arg == "--changed") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.changedCsv = *value;
        } else if (arg == "--world-to-camera") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseFloatCsv<16>(*value);
            if (!parsed)
                return std::nullopt;
            options.worldToCamera = *parsed;
        } else if (arg == "--camera-world-position") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseFloatCsv<3>(*value);
            if (!parsed)
                return std::nullopt;
            options.cameraWorldPosition = *parsed;
        } else if (arg == "--width" || arg == "--height") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseSize(*value);
            if (!parsed || *parsed == 0)
                return std::nullopt;
            if (arg == "--width")
                options.width = *parsed;
            else
                options.height = *parsed;
        } else if (arg == "--focal-x" || arg == "--focal-y" ||
                   arg == "--center-x" || arg == "--center-y" ||
                   arg == "--near" || arg == "--far" || arg == "--epsilon" ||
                   arg == "--background-r" || arg == "--background-g" ||
                   arg == "--background-b") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseDouble(*value);
            if (!parsed)
                return std::nullopt;
            if (arg == "--focal-x")
                options.focalX = static_cast<float>(*parsed);
            else if (arg == "--focal-y")
                options.focalY = static_cast<float>(*parsed);
            else if (arg == "--center-x")
                options.centerX = static_cast<float>(*parsed);
            else if (arg == "--center-y")
                options.centerY = static_cast<float>(*parsed);
            else if (arg == "--near")
                options.nearPlane = static_cast<float>(*parsed);
            else if (arg == "--far")
                options.farPlane = static_cast<float>(*parsed);
            else if (arg == "--epsilon")
                options.epsilon = *parsed;
            else if (arg == "--background-r")
                options.background[0] = static_cast<float>(*parsed);
            else if (arg == "--background-g")
                options.background[1] = static_cast<float>(*parsed);
            else
                options.background[2] = static_cast<float>(*parsed);
        } else if (arg == "--help") {
            std::cout
                << "Usage: maveb-cbrc-gaussian-oracle --before OLD.ply --after NEW.ply "
                   "--changed 1,4,9 [camera options]\n"
                << "  --width N --height N --focal-x F --focal-y F\n"
                << "  --center-x F --center-y F --near F --far F\n"
                << "  --world-to-camera m00,m01,...,m33 (row-major)\n"
                << "  --camera-world-position x,y,z\n"
                << "  --background-r F --background-g F --background-b F\n"
                << "  --epsilon F\n";
            std::exit(EXIT_SUCCESS);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            return std::nullopt;
        }
    }

    if (options.beforePath.empty() || options.afterPath.empty() ||
        options.changedCsv.empty() || options.epsilon < 0.0 ||
        options.focalX <= 0.0F || options.focalY <= 0.0F ||
        options.nearPlane <= 0.0F || options.farPlane <= options.nearPlane)
        return std::nullopt;
    return options;
}

[[nodiscard]] std::optional<std::vector<std::size_t>>
parseChangedIndices(std::string_view csv) {
    std::set<std::size_t> unique;
    std::size_t start{};
    while (start < csv.size()) {
        const std::size_t comma = csv.find(',', start);
        const std::size_t end = comma == std::string_view::npos ? csv.size() : comma;
        if (end == start)
            return std::nullopt;
        auto value = parseSize(csv.substr(start, end - start));
        if (!value || !unique.insert(*value).second)
            return std::nullopt;
        if (comma == std::string_view::npos)
            break;
        start = comma + 1;
    }
    if (unique.empty())
        return std::nullopt;
    return std::vector<std::size_t>(unique.begin(), unique.end());
}

[[nodiscard]] bool sameGaussian(const Gaussian& a, const Gaussian& b) noexcept {
    return a.position == b.position && a.logScale == b.logScale &&
           a.rotation == b.rotation && a.opacityLogit == b.opacityLogit &&
           a.dc == b.dc && a.rest == b.rest && a.restCount == b.restCount;
}

[[nodiscard]] double sceneColorCap(const GaussianAsset& before,
                                   const GaussianAsset& after) {
    double cap = 1.0; // reference background is clamped to [0,1].
    const auto accumulate = [&](const GaussianAsset& asset) -> bool {
        for (const Gaussian& primitive : asset.gaussians) {
            auto bound =
                aether::world_gaussian::gaussianRendererColorUpperBound(primitive);
            if (!bound)
                return false;
            for (const double channel : *bound)
                cap = std::max(cap, channel);
        }
        return true;
    };
    if (!accumulate(before) || !accumulate(after))
        return std::numeric_limits<double>::quiet_NaN();
    return cap;
}

} // namespace

int main(int argc, char** argv) try {
    auto options = parseOptions(argc, argv);
    if (!options) {
        std::cerr << "Invalid CBRC Gaussian oracle arguments\n";
        return EXIT_FAILURE;
    }
    auto changed = parseChangedIndices(options->changedCsv);
    if (!changed) {
        std::cerr << "Invalid --changed list; indices must be unique non-negative integers\n";
        return EXIT_FAILURE;
    }

    auto before = aether::gaussian::PlyLoader::load(options->beforePath);
    if (!before) {
        std::cerr << before.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto after = aether::gaussian::PlyLoader::load(options->afterPath);
    if (!after) {
        std::cerr << after.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (before->gaussians.size() != after->gaussians.size()) {
        std::cerr << "Oracle currently requires stable source-order Gaussian count\n";
        return EXIT_FAILURE;
    }

    std::vector<bool> isChanged(before->gaussians.size(), false);
    for (const std::size_t index : *changed) {
        if (index >= isChanged.size()) {
            std::cerr << "Changed Gaussian index is out of range: " << index << '\n';
            return EXIT_FAILURE;
        }
        isChanged[index] = true;
    }

    GaussianAsset beforeChanged;
    GaussianAsset afterChanged;
    beforeChanged.name = "before-changed";
    afterChanged.name = "after-changed";
    beforeChanged.sphericalHarmonicDegree = before->sphericalHarmonicDegree;
    afterChanged.sphericalHarmonicDegree = after->sphericalHarmonicDegree;
    beforeChanged.gaussians.reserve(changed->size());
    afterChanged.gaussians.reserve(changed->size());

    for (std::size_t index = 0; index < before->gaussians.size(); ++index) {
        if (isChanged[index]) {
            beforeChanged.gaussians.push_back(before->gaussians[index]);
            afterChanged.gaussians.push_back(after->gaussians[index]);
        } else if (!sameGaussian(before->gaussians[index], after->gaussians[index])) {
            std::cerr << "Undeclared Gaussian change at source index " << index
                      << "; certificate fails closed\n";
            return EXIT_FAILURE;
        }
    }

    ReferenceCamera camera;
    camera.width = options->width;
    camera.height = options->height;
    camera.focalX = options->focalX;
    camera.focalY = options->focalY;
    camera.centerX = options->centerX;
    camera.centerY = options->centerY;
    camera.nearPlane = options->nearPlane;
    camera.farPlane = options->farPlane;
    camera.cameraWorldPosition = options->cameraWorldPosition;
    camera.worldToCamera = options->worldToCamera;

    auto oldImage =
        aether::gaussian::ReferenceRasterizer::render(*before, camera, options->background);
    if (!oldImage) {
        std::cerr << oldImage.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto newImage =
        aether::gaussian::ReferenceRasterizer::render(*after, camera, options->background);
    if (!newImage) {
        std::cerr << newImage.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    const double colorCap = sceneColorCap(*before, *after);
    if (!std::isfinite(colorCap)) {
        std::cerr << "Unable to construct conservative scene color cap\n";
        return EXIT_FAILURE;
    }
    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(
            beforeChanged, afterChanged, camera, colorCap);
    if (!certificate) {
        std::cerr << certificate.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    double maximumActual{};
    double maximumBound{};
    std::size_t affectedPixels{};
    std::size_t certificateViolations{};
    std::size_t toleranceViolations{};

    for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual = std::max(
                actual,
                std::abs(static_cast<double>(oldImage->color[pixel][channel]) -
                         static_cast<double>(newImage->color[pixel][channel])));
        }
        const double bound = certificate->rgbLInfBounds[pixel];
        maximumActual = std::max(maximumActual, actual);
        maximumBound = std::max(maximumBound, bound);
        affectedPixels += static_cast<std::size_t>(bound > 0.0);
        certificateViolations +=
            static_cast<std::size_t>(actual > bound + 2.0e-6);
        toleranceViolations +=
            static_cast<std::size_t>(actual > options->epsilon + 2.0e-6);
    }

    const double effectivity =
        maximumBound / std::max(maximumActual, 1.0e-15);
    const double affectedFraction =
        static_cast<double>(affectedPixels) /
        static_cast<double>(oldImage->color.size());
    const bool withinTolerance = maximumBound <= options->epsilon;
    const bool certified = certificateViolations == 0;

    std::cout << std::setprecision(17)
              << "{"
              << "\"schemaVersion\":1,"
              << "\"experiment\":\"cbrc-gaussian-full-reference-oracle-v1\","
              << "\"method\":\"CBRC\","
              << "\"totalGaussians\":" << before->gaussians.size() << ','
              << "\"changedGaussians\":" << changed->size() << ','
              << "\"changedFraction\":"
              << static_cast<double>(changed->size()) /
                     static_cast<double>(before->gaussians.size()) << ','
              << "\"affectedPixels\":" << affectedPixels << ','
              << "\"affectedPixelFraction\":" << affectedFraction << ','
              << "\"colorUpperBound\":" << colorCap << ','
              << "\"qois\":{\"rgb_linf\":{"
              << "\"epsilon\":" << options->epsilon << ','
              << "\"certified_bound\":" << maximumBound << ','
              << "\"measured_full_reference_error\":" << maximumActual
              << "}},"
              << "\"effectivity\":" << effectivity << ','
              << "\"certificateViolationPixels\":" << certificateViolations << ','
              << "\"toleranceViolationPixels\":" << toleranceViolations << ','
              << "\"certified\":" << (certified ? "true" : "false") << ','
              << "\"withinTolerance\":" << (withinTolerance ? "true" : "false")
              << "}\n";

    if (!certified)
        return 4;
    if (!withinTolerance)
        return 3;
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "Unhandled CBRC Gaussian oracle exception: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "Unhandled CBRC Gaussian oracle exception\n";
    return EXIT_FAILURE;
}
