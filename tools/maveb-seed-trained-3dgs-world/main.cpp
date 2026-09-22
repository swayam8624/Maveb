#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/world/WorldArchive.hpp>
#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <compare>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct Options final {
    std::filesystem::path ply;
    std::filesystem::path output;
    float targetDiagonal{2.0F};
    float cellSize{};
    std::uint64_t timestamp{1'000'000'000ULL};
    bool preserveRawScale{};
    bool clampLogScale{};
    bool json{};
};

struct CellKey final {
    std::int32_t x{};
    std::int32_t y{};
    std::int32_t z{};
    auto operator<=>(const CellKey&) const = default;
};

struct Cluster final {
    std::vector<std::size_t> indices;
    simd_float3 minimum{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    simd_float3 maximum{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    simd_double3 sum{};
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

[[nodiscard]] std::optional<std::uint64_t> parseUnsigned(std::string_view text) {
    std::uint64_t value{};
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size())
        return std::nullopt;
    return value;
}

void usage() {
    std::cout << "Usage: maveb-seed-trained-3dgs-world --ply point_cloud.ply "
                 "--output world.aetherworld [options]\n"
                 "Options:\n"
                 "  --target-diagonal N   canonical scene diagonal, default 2.0\n"
                 "  --cell-size N         ownership grid cell size (default: diagonal/7)\n"
                 "  --timestamp NS        initial world timestamp\n"
                 "  --preserve-raw-scale  do not canonicalize PLY coordinates/scales\n"
                 "  --clamp-log-scale     clamp canonicalized log-scales to codec-safe [-30,30]\n"
                 "  --json                machine-readable summary\n";
}

[[nodiscard]] std::optional<Options> parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        const auto value = [&]() -> std::optional<std::string_view> {
            if (i + 1 >= argc)
                return std::nullopt;
            return std::string_view(argv[++i]);
        };
        if (arg == "--ply" || arg == "--output") {
            auto v = value();
            if (!v)
                return std::nullopt;
            if (arg == "--ply")
                options.ply = *v;
            else
                options.output = *v;
        } else if (arg == "--target-diagonal" || arg == "--cell-size") {
            auto v = value();
            auto parsed = v ? parseDouble(*v) : std::nullopt;
            if (!parsed)
                return std::nullopt;
            if (arg == "--target-diagonal")
                options.targetDiagonal = static_cast<float>(*parsed);
            else
                options.cellSize = static_cast<float>(*parsed);
        } else if (arg == "--timestamp") {
            auto v = value();
            auto parsed = v ? parseUnsigned(*v) : std::nullopt;
            if (!parsed)
                return std::nullopt;
            options.timestamp = *parsed;
        } else if (arg == "--preserve-raw-scale") {
            options.preserveRawScale = true;
        } else if (arg == "--clamp-log-scale") {
            options.clampLogScale = true;
        } else if (arg == "--json") {
            options.json = true;
        } else if (arg == "--help" || arg == "-h") {
            usage();
            std::exit(EXIT_SUCCESS);
        } else {
            return std::nullopt;
        }
    }
    if (options.ply.empty() || options.output.empty() || options.timestamp == 0 ||
        !std::isfinite(options.targetDiagonal) || options.targetDiagonal <= 0.0F ||
        !std::isfinite(options.cellSize) || options.cellSize < 0.0F) {
        return std::nullopt;
    }
    return options;
}

[[nodiscard]] aether::Result<void> atomicWrite(const std::filesystem::path& path,
                                               std::span<const std::byte> bytes) {
    if (bytes.empty())
        return aether::fail(aether::ErrorCode::invalidArgument, "Cannot write empty sidecar");
    std::error_code error;
    if (!path.parent_path().empty())
        std::filesystem::create_directories(path.parent_path(), error);
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to create sidecar directory",
                            error.message());
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream)
        return aether::fail(aether::ErrorCode::io, "Unable to write sidecar", path.string());
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to publish sidecar", error.message());
    }
    return {};
}

[[nodiscard]] std::pair<simd_float3, simd_float3>
assetBounds(const aether::gaussian::GaussianAsset& asset) {
    simd_float3 minimum{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    simd_float3 maximum{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    for (const auto& primitive : asset.gaussians) {
        const simd_float3 p{
            primitive.position[0],
            primitive.position[1],
            primitive.position[2],
        };
        minimum = simd_min(minimum, p);
        maximum = simd_max(maximum, p);
    }
    return {minimum, maximum};
}

[[nodiscard]] aether::Result<CellKey> keyFor(simd_float3 p, float cellSize) {
    const auto coordinate = [cellSize](float value) -> std::optional<std::int32_t> {
        const double scaled = std::floor(static_cast<double>(value) / cellSize);
        if (!std::isfinite(scaled) ||
            scaled < static_cast<double>(std::numeric_limits<std::int32_t>::min()) ||
            scaled > static_cast<double>(std::numeric_limits<std::int32_t>::max()))
            return std::nullopt;
        return static_cast<std::int32_t>(scaled);
    };
    const auto x = coordinate(p.x);
    const auto y = coordinate(p.y);
    const auto z = coordinate(p.z);
    if (!x || !y || !z)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "3DGS position exceeds ownership grid");
    return CellKey{*x, *y, *z};
}

[[nodiscard]] std::uint64_t signature(CellKey key, std::size_t count, std::uint64_t salt) {
    std::uint64_t hash = 1469598103934665603ULL ^ salt;
    const auto mix = [&hash](std::uint64_t value) {
        for (std::size_t byte = 0; byte < 8; ++byte) {
            hash ^= (value >> (byte * 8U)) & 0xffU;
            hash *= 1099511628211ULL;
        }
    };
    mix(static_cast<std::uint32_t>(key.x));
    mix(static_cast<std::uint32_t>(key.y));
    mix(static_cast<std::uint32_t>(key.z));
    mix(count);
    return hash;
}

} // namespace

int main(int argc, char** argv) try {
    const auto options = parseOptions(argc, argv);
    if (!options) {
        usage();
        return EXIT_FAILURE;
    }

    auto asset = aether::gaussian::PlyLoader::load(options->ply);
    if (!asset) {
        std::cerr << asset.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (asset->gaussians.empty()) {
        std::cerr << "Trained 3DGS PLY contains no Gaussians\n";
        return EXIT_FAILURE;
    }

    const auto [rawMin, rawMax] = assetBounds(*asset);
    const simd_float3 rawExtent = rawMax - rawMin;
    const float rawDiagonal = simd_length(rawExtent);
    if (!std::isfinite(rawDiagonal) || rawDiagonal <= 1.0e-8F) {
        std::cerr << "Trained 3DGS PLY has degenerate extent\n";
        return EXIT_FAILURE;
    }
    const simd_float3 rawCenter = (rawMin + rawMax) * 0.5F;
    const float normalization =
        options->preserveRawScale ? 1.0F : options->targetDiagonal / rawDiagonal;
    if (!std::isfinite(normalization) || normalization <= 0.0F) {
        std::cerr << "Invalid trained-3DGS normalization\n";
        return EXIT_FAILURE;
    }

    const float logNormalization = std::log(normalization);
    std::size_t clampedLogScaleComponents{};
    for (auto& primitive : asset->gaussians) {
        simd_float3 position{
            primitive.position[0],
            primitive.position[1],
            primitive.position[2],
        };
        if (!options->preserveRawScale)
            position = (position - rawCenter) * normalization;
        primitive.position = {position.x, position.y, position.z};
        if (!options->preserveRawScale) {
            for (float& logScale : primitive.logScale)
                logScale += logNormalization;
        }
        if (options->clampLogScale) {
            for (float& logScale : primitive.logScale) {
                const float clamped = std::clamp(logScale, -30.0F, 30.0F);
                if (clamped != logScale)
                    ++clampedLogScaleComponents;
                logScale = clamped;
            }
        }
    }

    const auto [minimum, maximum] = assetBounds(*asset);
    const float diagonal = simd_length(maximum - minimum);
    const float cellSize =
        options->cellSize > 0.0F ? options->cellSize : std::max(diagonal / 7.0F, 1.0e-4F);

    std::map<CellKey, Cluster> clusters;
    for (std::size_t index = 0; index < asset->gaussians.size(); ++index) {
        const auto& primitive = asset->gaussians[index];
        const simd_float3 position{
            primitive.position[0],
            primitive.position[1],
            primitive.position[2],
        };
        auto key = keyFor(position, cellSize);
        if (!key) {
            std::cerr << key.error().describe() << '\n';
            return EXIT_FAILURE;
        }
        float support{};
        for (const float logScale : primitive.logScale)
            support = std::max(support, 3.0F * std::exp(logScale));
        support = std::max(support, 1.0e-5F);

        Cluster& cluster = clusters[*key];
        cluster.indices.push_back(index);
        const simd_float3 supportVector{support, support, support};
        cluster.minimum = simd_min(cluster.minimum, position - supportVector);
        cluster.maximum = simd_max(cluster.maximum, position + supportVector);
        cluster.sum += simd_double3{position.x, position.y, position.z};
    }
    if (clusters.size() < 2) {
        std::cerr << "Trained 3DGS ownership grid produced fewer than two entities\n";
        return EXIT_FAILURE;
    }

    aether::world_gaussian::GaussianEntityOwnership ownership;
    ownership.owners.resize(asset->gaussians.size());
    aether::world::WorldSnapshot snapshot;
    snapshot.timestamp = options->timestamp;
    snapshot.entities.reserve(clusters.size());

    std::uint64_t entityId = 1;
    for (const auto& [key, cluster] : clusters) {
        const double inverse = 1.0 / static_cast<double>(cluster.indices.size());
        const simd_float3 centroid{
            static_cast<float>(cluster.sum.x * inverse),
            static_cast<float>(cluster.sum.y * inverse),
            static_cast<float>(cluster.sum.z * inverse),
        };
        aether::world::EntityState entity;
        entity.id = aether::world::EntityId{entityId};
        entity.name = "trained-3dgs-cell-" + std::to_string(entityId);
        entity.semanticLabel = "spatial-trained-3dgs-cell";
        entity.transform.translation = centroid;
        entity.worldBounds.minimum = cluster.minimum;
        entity.worldBounds.maximum = cluster.maximum;
        entity.representation = aether::world::RepresentationKind::gaussian;
        entity.geometrySignature = signature(key, cluster.indices.size(), 0x3344475347454fULL);
        entity.appearanceSignature = signature(key, cluster.indices.size(), 0x33444753415050ULL);
        entity.confidence = 1.0F;
        entity.lastObserved = options->timestamp;
        snapshot.entities.push_back(entity);
        for (const std::size_t index : cluster.indices)
            ownership.owners[index] = entity.id;
        ++entityId;
    }

    aether::world::WorldTimeline timeline;
    auto revision = timeline.append(std::move(snapshot));
    if (!revision) {
        std::cerr << revision.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    std::error_code error;
    if (!options->output.parent_path().empty()) {
        std::filesystem::create_directories(options->output.parent_path(), error);
        if (error) {
            std::cerr << "Unable to create output directory: " << error.message() << '\n';
            return EXIT_FAILURE;
        }
    }
    if (auto saved = aether::world::saveWorldArchive(options->output, timeline, entityId); !saved) {
        std::cerr << saved.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    auto gaussianBytes = aether::gaussian::GaussianCodec::encode(*asset);
    auto ownershipBytes = aether::world_gaussian::GaussianOwnershipCodec::encode(ownership);
    if (!gaussianBytes || !ownershipBytes) {
        std::cerr << "Unable to encode trained-3DGS world sidecars\n";
        return EXIT_FAILURE;
    }
    const std::string worldPath = options->output.string();
    const std::filesystem::path gaussianPath = worldPath + ".gaussians.r1.bin";
    const std::filesystem::path ownershipPath = worldPath + ".ownership.r1.bin";
    if (auto written = atomicWrite(gaussianPath, *gaussianBytes); !written) {
        std::cerr << written.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (auto written = atomicWrite(ownershipPath, *ownershipBytes); !written) {
        std::cerr << written.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    const std::string_view scaleSource =
        options->preserveRawScale ? "source-preserved" : "canonical-normalization-not-measured";

    std::ostringstream summary;
    summary << std::setprecision(17);
    summary << "{\"schemaVersion\":1,\"artifact\":\"maveb-trained-3dgs-world-seed\",";
    summary << "\"sourcePly\":\"" << options->ply.string() << "\",";
    summary << "\"world\":\"" << options->output.string() << "\",";
    summary << "\"gaussians\":" << asset->gaussians.size() << ',';
    summary << "\"shDegree\":" << asset->sphericalHarmonicDegree << ',';
    summary << "\"entities\":" << timeline.latest()->entities.size() << ',';
    summary << "\"rawDiagonal\":" << rawDiagonal << ',';
    summary << "\"canonicalDiagonal\":" << diagonal << ',';
    summary << "\"uniformScale\":" << normalization << ',';
    summary << "\"scaleSource\":\"" << scaleSource << "\",";
    summary << "\"logScaleClampEnabled\":" << (options->clampLogScale ? "true" : "false") << ',';
    summary << "\"logScaleClampedComponents\":" << clampedLogScaleComponents << ',';
    summary << "\"logScaleClampRange\":[-30,30],";
    summary << "\"ownershipMode\":\"deterministic-spatial-grid-not-semantic\",";
    summary << "\"representation\":\"trained-3dgs-preserved-sh-opacity-rotation-with-canonical-scale\"";
    summary << "}\n";
    std::cout << summary.str();
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "maveb-seed-trained-3dgs-world: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "maveb-seed-trained-3dgs-world: unknown failure\n";
    return EXIT_FAILURE;
}
