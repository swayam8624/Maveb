#include <aether/world_gaussian/GaussianLocalUpdate.hpp>
#include <aether/world_gaussian/GaussianSpatialIndex.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::RegionKey;
using aether::world::RegionUpdate;
using aether::world::SelectiveUpdatePlan;
using aether::world_gaussian::GaussianSpatialIndex;

struct Options final {
    std::size_t gaussians{1'000'000};
    std::size_t gaussiansPerCell{8};
    double dirtyFraction{0.01};
    float cellSizeMeters{1.0F};
    std::size_t repeats{5};
};

[[nodiscard]] std::optional<std::size_t> parseSize(std::string_view value) {
    try {
        const auto parsed = std::stoull(std::string(value));
        return static_cast<std::size_t>(parsed);
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] std::optional<double> parseDouble(std::string_view value) {
    try {
        return std::stod(std::string(value));
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] std::optional<Options> parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        const auto requireValue = [&](std::string_view name) -> std::optional<std::string_view> {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << name << '\n';
                return std::nullopt;
            }
            ++i;
            return std::string_view(argv[i]);
        };

        if (arg == "--gaussians") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseSize(*value);
            if (!parsed || *parsed == 0)
                return std::nullopt;
            options.gaussians = *parsed;
        } else if (arg == "--gaussians-per-cell") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseSize(*value);
            if (!parsed || *parsed == 0)
                return std::nullopt;
            options.gaussiansPerCell = *parsed;
        } else if (arg == "--dirty-fraction") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseDouble(*value);
            if (!parsed || *parsed <= 0.0 || *parsed > 1.0)
                return std::nullopt;
            options.dirtyFraction = *parsed;
        } else if (arg == "--cell-size") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseDouble(*value);
            if (!parsed || *parsed <= 0.0)
                return std::nullopt;
            options.cellSizeMeters = static_cast<float>(*parsed);
        } else if (arg == "--repeats") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseSize(*value);
            if (!parsed || *parsed == 0)
                return std::nullopt;
            options.repeats = *parsed;
        } else if (arg == "--help") {
            std::cout << "Usage: maveb-gaussian-locality-bench [options]\n"
                      << "  --gaussians N\n"
                      << "  --gaussians-per-cell N\n"
                      << "  --dirty-fraction F\n"
                      << "  --cell-size metres\n"
                      << "  --repeats N\n";
            std::exit(EXIT_SUCCESS);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            return std::nullopt;
        }
    }
    return options;
}

[[nodiscard]] double elapsedMs(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

[[nodiscard]] GaussianAsset makeAsset(const Options& options, std::vector<RegionKey>& cells) {
    const std::size_t cellCount =
        (options.gaussians + options.gaussiansPerCell - 1) / options.gaussiansPerCell;
    const std::size_t side =
        static_cast<std::size_t>(std::ceil(std::cbrt(static_cast<double>(cellCount))));

    GaussianAsset asset;
    asset.name = "gaussian-locality-benchmark";
    asset.gaussians.reserve(options.gaussians);
    cells.reserve(cellCount);

    for (std::size_t cell = 0; cell < cellCount; ++cell) {
        const std::int32_t x = static_cast<std::int32_t>(cell % side);
        const std::int32_t y = static_cast<std::int32_t>((cell / side) % side);
        const std::int32_t z = static_cast<std::int32_t>(cell / (side * side));
        cells.push_back(RegionKey{x, y, z});

        for (std::size_t local = 0;
             local < options.gaussiansPerCell && asset.gaussians.size() < options.gaussians;
             ++local) {
            const float jitter = 0.05F + 0.8F * static_cast<float>(local + 1) /
                                             static_cast<float>(options.gaussiansPerCell + 1);
            Gaussian primitive;
            primitive.position = {
                (static_cast<float>(x) + jitter) * options.cellSizeMeters,
                (static_cast<float>(y) + 0.25F + 0.01F * static_cast<float>(local)) *
                    options.cellSizeMeters,
                (static_cast<float>(z) + 0.35F + 0.005F * static_cast<float>(local)) *
                    options.cellSizeMeters,
            };
            asset.gaussians.push_back(primitive);
        }
    }
    return asset;
}

[[nodiscard]] SelectiveUpdatePlan makePlan(const Options& options,
                                           const std::vector<RegionKey>& cells) {
    SelectiveUpdatePlan plan;
    plan.cellSizeMeters = options.cellSizeMeters;
    const std::size_t dirtyCount =
        std::max<std::size_t>(1, static_cast<std::size_t>(std::ceil(
                                     static_cast<double>(cells.size()) * options.dirtyFraction)));
    plan.dirtyRegions.reserve(dirtyCount);
    for (std::size_t index = 0; index < dirtyCount; ++index) {
        RegionUpdate update;
        update.key = cells[index];
        plan.dirtyRegions.push_back(update);
    }
    return plan;
}

} // namespace

int main(int argc, char** argv) try {
    auto options = parseOptions(argc, argv);
    if (!options) {
        std::cerr << "Invalid benchmark arguments\n";
        return EXIT_FAILURE;
    }

    std::vector<RegionKey> cells;
    GaussianAsset asset = makeAsset(*options, cells);
    const SelectiveUpdatePlan plan = makePlan(*options, cells);

    const auto buildStart = Clock::now();
    auto spatialIndex = GaussianSpatialIndex::build(asset, options->cellSizeMeters);
    const auto buildEnd = Clock::now();
    if (!spatialIndex) {
        std::cerr << spatialIndex.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    double scanTotalMs{};
    double indexedTotalMs{};
    aether::world_gaussian::GaussianLocalUpdateSelection scanned;
    aether::world_gaussian::GaussianLocalUpdateSelection indexed;

    for (std::size_t repeat = 0; repeat < options->repeats; ++repeat) {
        const auto scanStart = Clock::now();
        auto scan = aether::world_gaussian::selectGaussiansForLocalUpdate(asset, plan);
        const auto scanEnd = Clock::now();
        if (!scan) {
            std::cerr << scan.error().describe() << '\n';
            return EXIT_FAILURE;
        }
        scanTotalMs += elapsedMs(scanStart, scanEnd);
        scanned = std::move(*scan);

        const auto indexedStart = Clock::now();
        auto selected = aether::world_gaussian::selectGaussiansForLocalUpdateIndexed(asset, plan,
                                                                                     *spatialIndex);
        const auto indexedEnd = Clock::now();
        if (!selected) {
            std::cerr << selected.error().describe() << '\n';
            return EXIT_FAILURE;
        }
        indexedTotalMs += elapsedMs(indexedStart, indexedEnd);
        indexed = std::move(*selected);
    }

    if (scanned.gaussianIndices != indexed.gaussianIndices) {
        std::cerr << "Indexed selection does not match full scan\n";
        return EXIT_FAILURE;
    }

    const auto stats = spatialIndex->statistics();
    std::cout << std::fixed << std::setprecision(6) << "{"
              << "\"schemaVersion\":1,"
              << "\"benchmark\":\"maveb-gaussian-locality-bench\","
              << "\"gaussians\":" << asset.gaussians.size() << ','
              << "\"gaussiansPerCell\":" << options->gaussiansPerCell << ','
              << "\"occupiedRegions\":" << stats.occupiedRegions << ','
              << "\"dirtyRegions\":" << plan.dirtyRegions.size() << ','
              << "\"dirtyFraction\":" << options->dirtyFraction << ','
              << "\"selectedGaussians\":" << indexed.gaussianIndices.size() << ','
              << "\"scanInspections\":" << scanned.inspectedGaussians << ','
              << "\"indexedInspections\":" << indexed.inspectedGaussians << ','
              << "\"indexBuildMs\":" << elapsedMs(buildStart, buildEnd) << ','
              << "\"scanMeanMs\":" << scanTotalMs / static_cast<double>(options->repeats) << ','
              << "\"indexedMeanMs\":" << indexedTotalMs / static_cast<double>(options->repeats)
              << ',' << "\"repeats\":" << options->repeats << ','
              << "\"exactSelectionAgreement\":true"
              << "}\n";
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "Unhandled benchmark exception: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "Unhandled benchmark exception\n";
    return EXIT_FAILURE;
}
