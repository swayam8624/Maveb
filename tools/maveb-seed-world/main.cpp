#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/hybrid/ProxyPlyLoader.hpp>
#include <aether/world/WorldArchive.hpp>
#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <algorithm>
#include <array>
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

constexpr float kShC0 = 0.28209479177387814F;

struct Options final {
    std::filesystem::path proxy;
    std::filesystem::path output;
    float cellSizeMeters{};
    float gaussianScaleMeters{};
    float opacity{0.85F};
    std::uint64_t timestamp{1'000'000'000ULL};
    std::size_t maximumGaussians{1'000'000};
    bool json{};
};

struct CellKey final {
    std::int32_t x{};
    std::int32_t y{};
    std::int32_t z{};
    auto operator<=>(const CellKey&) const = default;
};

struct Cluster final {
    std::vector<std::size_t> gaussianIndices;
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
    double confidenceSum{};
};

[[nodiscard]] std::optional<std::uint64_t> parseUnsigned(std::string_view text) {
    std::uint64_t value{};
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size())
        return std::nullopt;
    return value;
}

[[nodiscard]] std::optional<double> parseDouble(std::string_view text) {
    std::istringstream stream{std::string(text)};
    stream >> std::noskipws;
    double value{};
    stream >> value;
    if (!stream || !stream.eof() || !std::isfinite(value))
        return std::nullopt;
    return value;
}

void usage() {
    std::cout << "Usage: maveb-seed-world --proxy proxy.ply --output world.aetherworld [options]\n"
              << "Options:\n"
              << "  --cell-size METRES       spatial ownership cell size (default: auto)\n"
              << "  --gaussian-scale METRES  isotropic Gaussian sigma (default: auto)\n"
              << "  --opacity VALUE          Gaussian opacity in (0,1), default 0.85\n"
              << "  --timestamp NS           initial world timestamp, default 1000000000\n"
              << "  --max-gaussians N        deterministic sample cap, default 1000000\n"
              << "  --json                   machine-readable summary\n";
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

        if (arg == "--proxy") {
            auto v = value();
            if (!v)
                return std::nullopt;
            options.proxy = *v;
        } else if (arg == "--output") {
            auto v = value();
            if (!v)
                return std::nullopt;
            options.output = *v;
        } else if (arg == "--cell-size" || arg == "--gaussian-scale" || arg == "--opacity") {
            auto v = value();
            auto parsed = v ? parseDouble(*v) : std::nullopt;
            if (!parsed)
                return std::nullopt;
            if (arg == "--cell-size")
                options.cellSizeMeters = static_cast<float>(*parsed);
            else if (arg == "--gaussian-scale")
                options.gaussianScaleMeters = static_cast<float>(*parsed);
            else
                options.opacity = static_cast<float>(*parsed);
        } else if (arg == "--timestamp" || arg == "--max-gaussians") {
            auto v = value();
            auto parsed = v ? parseUnsigned(*v) : std::nullopt;
            if (!parsed)
                return std::nullopt;
            if (arg == "--timestamp")
                options.timestamp = *parsed;
            else
                options.maximumGaussians = static_cast<std::size_t>(*parsed);
        } else if (arg == "--json") {
            options.json = true;
        } else if (arg == "--help" || arg == "-h") {
            usage();
            std::exit(EXIT_SUCCESS);
        } else {
            return std::nullopt;
        }
    }

    if (options.proxy.empty() || options.output.empty() || options.timestamp == 0 ||
        options.maximumGaussians == 0 || !std::isfinite(options.opacity) ||
        options.opacity <= 0.0F || options.opacity >= 1.0F ||
        !std::isfinite(options.cellSizeMeters) || options.cellSizeMeters < 0.0F ||
        !std::isfinite(options.gaussianScaleMeters) || options.gaussianScaleMeters < 0.0F) {
        return std::nullopt;
    }
    return options;
}

[[nodiscard]] aether::Result<void> atomicWrite(const std::filesystem::path& path,
                                               std::span<const std::byte> bytes) {
    if (bytes.empty())
        return aether::fail(aether::ErrorCode::invalidArgument, "Cannot write empty sidecar",
                            path.string());
    std::error_code error;
    std::filesystem::create_directories(path.parent_path(), error);
    if (error && !path.parent_path().empty())
        return aether::fail(aether::ErrorCode::io, "Unable to create output directory",
                            error.message());

    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to write sidecar", path.string());
    }
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to publish sidecar", error.message());
    }
    return {};
}

[[nodiscard]] float extentDiagonal(const aether::hybrid::ProxyMesh& mesh) {
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
    for (const auto& vertex : mesh.vertices) {
        const simd_float3 p{vertex.position[0], vertex.position[1], vertex.position[2]};
        minimum = simd_min(minimum, p);
        maximum = simd_max(maximum, p);
    }
    return simd_length(maximum - minimum);
}

[[nodiscard]] aether::Result<CellKey> keyFor(simd_float3 p, float cellSize) {
    auto coordinate = [cellSize](float value) -> std::optional<std::int32_t> {
        const double scaled = std::floor(static_cast<double>(value) / cellSize);
        if (!std::isfinite(scaled) ||
            scaled < static_cast<double>(std::numeric_limits<std::int32_t>::min()) ||
            scaled > static_cast<double>(std::numeric_limits<std::int32_t>::max())) {
            return std::nullopt;
        }
        return static_cast<std::int32_t>(scaled);
    };
    auto x = coordinate(p.x);
    auto y = coordinate(p.y);
    auto z = coordinate(p.z);
    if (!x || !y || !z)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Proxy vertex exceeds spatial ownership grid");
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

[[nodiscard]] float colorChannel(std::uint32_t rgba, std::uint32_t shift) {
    return static_cast<float>((rgba >> shift) & 0xffU) / 255.0F;
}

} // namespace

int main(int argc, char** argv) try {
    auto options = parseOptions(argc, argv);
    if (!options) {
        usage();
        return EXIT_FAILURE;
    }

    auto mesh = aether::hybrid::ProxyPlyLoader::load(options->proxy);
    if (!mesh) {
        std::cerr << mesh.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (mesh->vertices.empty()) {
        std::cerr << "Proxy mesh contains no vertices\n";
        return EXIT_FAILURE;
    }

    const float diagonal = extentDiagonal(*mesh);
    if (!std::isfinite(diagonal) || diagonal <= 1.0e-6F) {
        std::cerr << "Proxy mesh has degenerate spatial extent\n";
        return EXIT_FAILURE;
    }

    const float cellSize = options->cellSizeMeters > 0.0F
                               ? options->cellSizeMeters
                               : std::clamp(diagonal / 7.0F, 0.03F, 1.0F);
    const std::size_t sampleStride = std::max<std::size_t>(
        1, (mesh->vertices.size() + options->maximumGaussians - 1) / options->maximumGaussians);
    const std::size_t sampledCount = (mesh->vertices.size() + sampleStride - 1) / sampleStride;
    const float densityScale =
        static_cast<float>(0.65 * static_cast<double>(diagonal) /
                           std::cbrt(static_cast<double>(
                               std::max<std::size_t>(sampledCount, 1))));
    const float gaussianScale =
        options->gaussianScaleMeters > 0.0F
            ? options->gaussianScaleMeters
            : std::clamp(densityScale, 0.002F, std::max(0.002F, cellSize / 5.0F));

    aether::gaussian::GaussianAsset asset;
    asset.name = options->proxy.stem().string() + "-real-capture-seed";
    asset.sphericalHarmonicDegree = 0;
    asset.gaussians.reserve(sampledCount);

    std::map<CellKey, Cluster> clusters;
    const float opacityLogit = std::log(options->opacity / (1.0F - options->opacity));
    const float logScale = std::log(gaussianScale);

    for (std::size_t vertexIndex = 0; vertexIndex < mesh->vertices.size();
         vertexIndex += sampleStride) {
        const auto& vertex = mesh->vertices[vertexIndex];
        const simd_float3 position{vertex.position[0], vertex.position[1], vertex.position[2]};
        auto key = keyFor(position, cellSize);
        if (!key) {
            std::cerr << key.error().describe() << '\n';
            return EXIT_FAILURE;
        }

        aether::gaussian::Gaussian gaussian;
        gaussian.position = vertex.position;
        gaussian.logScale = {logScale, logScale, logScale};
        gaussian.rotation = {1.0F, 0.0F, 0.0F, 0.0F};
        gaussian.opacityLogit = opacityLogit;
        gaussian.dc = {
            (colorChannel(vertex.colorRgba, 0) - 0.5F) / kShC0,
            (colorChannel(vertex.colorRgba, 8) - 0.5F) / kShC0,
            (colorChannel(vertex.colorRgba, 16) - 0.5F) / kShC0,
        };
        gaussian.restCount = 0;

        const std::size_t gaussianIndex = asset.gaussians.size();
        asset.gaussians.push_back(gaussian);

        Cluster& cluster = clusters[*key];
        cluster.gaussianIndices.push_back(gaussianIndex);
        cluster.minimum = simd_min(cluster.minimum, position);
        cluster.maximum = simd_max(cluster.maximum, position);
        cluster.sum += simd_double3{position.x, position.y, position.z};
        cluster.confidenceSum += std::clamp(static_cast<double>(vertex.confidence), 0.0, 1.0);
    }

    if (clusters.size() < 2) {
        std::cerr << "Spatial seeding produced fewer than two owned entities; "
                     "capture a larger scene or use a smaller --cell-size\n";
        return EXIT_FAILURE;
    }

    aether::world_gaussian::GaussianEntityOwnership ownership;
    ownership.owners.resize(asset.gaussians.size());

    aether::world::WorldSnapshot snapshot;
    snapshot.timestamp = options->timestamp;
    snapshot.entities.reserve(clusters.size());

    std::uint64_t entityId = 1;
    for (const auto& [key, cluster] : clusters) {
        if (cluster.gaussianIndices.empty())
            continue;
        const double inverseCount = 1.0 / static_cast<double>(cluster.gaussianIndices.size());
        const simd_float3 centroid{
            static_cast<float>(cluster.sum.x * inverseCount),
            static_cast<float>(cluster.sum.y * inverseCount),
            static_cast<float>(cluster.sum.z * inverseCount),
        };
        const float support = 3.0F * gaussianScale;

        aether::world::EntityState entity;
        entity.id = aether::world::EntityId{entityId};
        entity.name = "capture-cell-" + std::to_string(entityId);
        entity.semanticLabel = "spatial-capture-cell";
        entity.transform.translation = centroid;
        entity.worldBounds.minimum = cluster.minimum - simd_float3{support, support, support};
        entity.worldBounds.maximum = cluster.maximum + simd_float3{support, support, support};
        entity.representation = aether::world::RepresentationKind::gaussian;
        entity.geometrySignature = signature(key, cluster.gaussianIndices.size(), 0x47534dULL);
        entity.appearanceSignature = signature(key, cluster.gaussianIndices.size(), 0x434f4cULL);
        entity.confidence =
            static_cast<float>(std::clamp(cluster.confidenceSum * inverseCount, 0.0, 1.0));
        entity.lastObserved = options->timestamp;
        snapshot.entities.push_back(entity);

        for (const std::size_t index : cluster.gaussianIndices)
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
            std::cerr << "Unable to create world output directory: " << error.message() << '\n';
            return EXIT_FAILURE;
        }
    }

    auto saved = aether::world::saveWorldArchive(options->output, timeline, entityId);
    if (!saved) {
        std::cerr << saved.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    auto gaussianBytes = aether::gaussian::GaussianCodec::encode(asset);
    auto ownershipBytes = aether::world_gaussian::GaussianOwnershipCodec::encode(ownership);
    if (!gaussianBytes || !ownershipBytes) {
        std::cerr << "Unable to encode seeded Gaussian world sidecars\n";
        return EXIT_FAILURE;
    }

    const auto gaussianPath = std::filesystem::path(options->output.string() + ".gaussians.r1.bin");
    const auto ownershipPath =
        std::filesystem::path(options->output.string() + ".ownership.r1.bin");
    if (auto result = atomicWrite(gaussianPath, *gaussianBytes); !result) {
        std::cerr << result.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (auto result = atomicWrite(ownershipPath, *ownershipBytes); !result) {
        std::cerr << result.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    if (options->json) {
        std::cout << std::setprecision(17)
                  << "{\"schemaVersion\":1,\"artifact\":\"maveb-real-capture-world-seed\","
                  << "\"world\":\"" << options->output.string() << "\","
                  << "\"sourceProxy\":\"" << options->proxy.string() << "\","
                  << "\"sourceVertices\":" << mesh->vertices.size() << ','
                  << "\"gaussians\":" << asset.gaussians.size() << ','
                  << "\"entities\":" << timeline.latest()->entities.size() << ','
                  << "\"sampleStride\":" << sampleStride << ',' << "\"cellSizeMetres\":"
                  << cellSize << ',' << "\"gaussianScaleMetres\":" << gaussianScale << ','
                  << "\"opacity\":" << options->opacity << ','
                  << "\"ownershipMode\":\"deterministic-spatial-grid-not-semantic\""
                  << "}\n";
    } else {
        std::cout << "Seeded real persistent world from " << mesh->vertices.size()
                  << " proxy vertices: " << asset.gaussians.size() << " Gaussians, "
                  << timeline.latest()->entities.size() << " spatial owners\n"
                  << "World: " << options->output << '\n'
                  << "Gaussian sidecar: " << gaussianPath << '\n'
                  << "Ownership sidecar: " << ownershipPath << '\n';
    }
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "maveb-seed-world: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "maveb-seed-world: unknown failure\n";
    return EXIT_FAILURE;
}
