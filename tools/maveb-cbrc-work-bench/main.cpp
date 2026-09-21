#include <aether/gaussian/GaussianAsset.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;

struct Options final {
    std::size_t gaussians{1'000'000};
    std::size_t publicationBytes{256'000'000};
    std::size_t pixels{std::size_t{1280} * std::size_t{720}};
    std::size_t repeats{9};
    std::string calibrationId{"native-host"};
};

volatile double gSinkDouble{};
volatile std::uint64_t gSinkInteger{};

[[nodiscard]] std::optional<std::size_t> parseSize(std::string_view text) {
    try {
        std::size_t consumed{};
        const auto value = std::stoull(std::string(text), &consumed);
        if (consumed != text.size() || value == 0)
            return std::nullopt;
        return static_cast<std::size_t>(value);
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] std::optional<Options> parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        const auto requireValue = [&]() -> std::optional<std::string_view> {
            if (i + 1 >= argc)
                return std::nullopt;
            return std::string_view(argv[++i]);
        };
        if (arg == "--gaussians" || arg == "--publication-bytes" || arg == "--pixels" ||
            arg == "--repeats") {
            auto value = requireValue();
            auto parsed = value ? parseSize(*value) : std::nullopt;
            if (!parsed)
                return std::nullopt;
            if (arg == "--gaussians")
                options.gaussians = *parsed;
            else if (arg == "--publication-bytes")
                options.publicationBytes = *parsed;
            else if (arg == "--pixels")
                options.pixels = *parsed;
            else
                options.repeats = *parsed;
        } else if (arg == "--calibration-id") {
            auto value = requireValue();
            if (!value || value->empty())
                return std::nullopt;
            options.calibrationId = *value;
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: maveb-cbrc-work-bench [--gaussians N] "
                         "[--publication-bytes N] [--pixels N] [--repeats N] "
                         "[--calibration-id ID]\n";
            std::exit(EXIT_SUCCESS);
        } else {
            return std::nullopt;
        }
    }
    return options;
}

[[nodiscard]] double elapsedMs(Clock::time_point begin, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - begin).count();
}

void row(std::string_view domain, std::string_view unit, std::size_t units, double elapsed,
         std::string_view calibrationId) {
    std::cout << std::setprecision(17);
    std::cout << "{\"domain\":\"" << domain << "\",";
    std::cout << "\"unit\":\"" << unit << "\",";
    std::cout << "\"units\":" << units << ',';
    std::cout << "\"elapsed_ms\":" << elapsed << ',';
    std::cout << "\"baseline_ms\":0.0,";
    std::cout << "\"calibration_id\":\"" << calibrationId << "\"}\n";
}

} // namespace

int main(int argc, char** argv) try {
    const auto options = parseOptions(argc, argv);
    if (!options) {
        std::cerr << "Invalid CBRC work-bench arguments\n";
        return EXIT_FAILURE;
    }

    std::vector<aether::gaussian::Gaussian> gaussians(options->gaussians);
    for (std::size_t index = 0; index < gaussians.size(); ++index) {
        const float value = static_cast<float>(index % 1024) * 0.001F;
        gaussians[index].position = {value, value * 0.5F, 1.0F + value * 0.25F};
    }
    std::vector<std::byte> publicationSource(options->publicationBytes, std::byte{0x5a});
    std::vector<std::byte> publicationDestination(options->publicationBytes);
    std::vector<std::uint8_t> temporalMask(options->pixels, 0);

    for (std::size_t repeat = 0; repeat < options->repeats; ++repeat) {
        double sum{};
        const auto inspectBegin = Clock::now();
        for (const auto& gaussian : gaussians)
            sum += gaussian.position[0] + gaussian.position[1] + gaussian.position[2];
        const auto inspectEnd = Clock::now();
        gSinkDouble = sum;
        const double inspectMs = elapsedMs(inspectBegin, inspectEnd);
        row("gaussiansInspected", "gaussians", gaussians.size(), inspectMs,
            options->calibrationId);

        const float delta = 1.0e-6F * static_cast<float>(repeat + 1);
        const auto updateBegin = Clock::now();
        for (auto& gaussian : gaussians)
            gaussian.position[0] += delta;
        const auto updateEnd = Clock::now();
        gSinkDouble = gaussians.back().position[0];
        const double updateMs = elapsedMs(updateBegin, updateEnd);
        row("gaussiansUpdated", "gaussians", gaussians.size(), updateMs,
            options->calibrationId);

        const auto publishBegin = Clock::now();
        std::memcpy(publicationDestination.data(), publicationSource.data(),
                    publicationSource.size());
        const auto publishEnd = Clock::now();
        const auto firstByte = static_cast<std::uint64_t>(publicationDestination.front());
        const auto lastByte = static_cast<std::uint64_t>(publicationDestination.back());
        gSinkInteger = firstByte + lastByte;
        const double publicationMs = elapsedMs(publishBegin, publishEnd);
        row("gpuPublicationBytes", "bytes", publicationSource.size(), publicationMs,
            options->calibrationId);

        const auto temporalBegin = Clock::now();
        std::fill(temporalMask.begin(), temporalMask.end(),
                  static_cast<std::uint8_t>((repeat & 1U) != 0U));
        const auto temporalEnd = Clock::now();
        gSinkInteger = temporalMask.front() + temporalMask.back();
        const double temporalMs = elapsedMs(temporalBegin, temporalEnd);
        row("temporalPixelsInvalidated", "pixels", temporalMask.size(), temporalMs,
            options->calibrationId);
    }

    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "maveb-cbrc-work-bench: " << error.what() << '\n';
    return EXIT_FAILURE;
}
