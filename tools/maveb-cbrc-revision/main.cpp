#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/revision/RevisionPlanner.hpp>
#include <aether/world/WorldModel.hpp>
#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>
#include <aether/world_gaussian/GaussianLocalUpdate.hpp>
#include <aether/world_gaussian/GaussianOverlaySpatialIndex.hpp>
#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>
#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

using aether::gaussian::GaussianAsset;
using aether::gaussian::ReferenceCamera;
using aether::world::EntityId;
using aether::world::PersistentWorldModel;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianOverlaySpatialIndex;

struct Options final {
    std::filesystem::path archive;
    std::filesystem::path outputDir;
    std::uint64_t entity{};
    std::uint64_t timestamp{};
    simd_float3 target{};
    bool haveTarget{};
    std::size_t width{1280};
    std::size_t height{720};
    float focalX{900.0F};
    float focalY{900.0F};
    float centerX{640.0F};
    float centerY{360.0F};
    float nearPlane{0.01F};
    float farPlane{10'000.0F};
    std::array<float, 3> cameraWorldPosition{};
    std::array<float, 16> worldToCamera{
        1.0F, 0.0F, 0.0F, 0.0F,
        0.0F, 1.0F, 0.0F, 0.0F,
        0.0F, 0.0F, 1.0F, 0.0F,
        0.0F, 0.0F, 0.0F, 1.0F,
    };
    double epsilon{1.0 / 255.0};
    double historyWeight{0.9};
    bool historyStable{true};
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

[[nodiscard]] std::optional<std::uint64_t> parseU64(std::string_view text) {
    try {
        std::size_t consumed{};
        const auto value = std::stoull(std::string(text), &consumed);
        if (consumed != text.size())
            return std::nullopt;
        return static_cast<std::uint64_t>(value);
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

        if (arg == "--archive") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.archive = *value;
        } else if (arg == "--output-dir") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.outputDir = *value;
        } else if (arg == "--entity" || arg == "--timestamp" ||
                   arg == "--width" || arg == "--height") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseU64(*value);
            if (!parsed)
                return std::nullopt;
            if (arg == "--entity")
                options.entity = *parsed;
            else if (arg == "--timestamp")
                options.timestamp = *parsed;
            else if (arg == "--width")
                options.width = static_cast<std::size_t>(*parsed);
            else
                options.height = static_cast<std::size_t>(*parsed);
        } else if (arg == "--target") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            auto parsed = parseFloatCsv<3>(*value);
            if (!parsed)
                return std::nullopt;
            options.target = {(*parsed)[0], (*parsed)[1], (*parsed)[2]};
            options.haveTarget = true;
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
        } else if (arg == "--focal-x" || arg == "--focal-y" ||
                   arg == "--center-x" || arg == "--center-y" ||
                   arg == "--near" || arg == "--far" ||
                   arg == "--epsilon" || arg == "--history-weight") {
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
            else
                options.historyWeight = *parsed;
        } else if (arg == "--history-unstable") {
            options.historyStable = false;
        } else if (arg == "--help") {
            std::cout
                << "Usage: maveb-cbrc-revision --archive WORLD --entity ID "
                   "--target x,y,z --timestamp NS --output-dir DIR [camera options]\n"
                << "  --width N --height N --focal-x F --focal-y F\n"
                << "  --center-x F --center-y F --near F --far F\n"
                << "  --world-to-camera m00,...,m33 --camera-world-position x,y,z\n"
                << "  --epsilon E --history-weight W --history-unstable\n";
            std::exit(EXIT_SUCCESS);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            return std::nullopt;
        }
    }

    if (options.archive.empty() || options.outputDir.empty() || options.entity == 0 ||
        options.timestamp == 0 || !options.haveTarget || options.width == 0 ||
        options.height == 0 || options.focalX <= 0.0F || options.focalY <= 0.0F ||
        options.nearPlane <= 0.0F || options.farPlane <= options.nearPlane ||
        !std::isfinite(options.epsilon) || options.epsilon < 0.0 ||
        !std::isfinite(options.historyWeight) || options.historyWeight < 0.0 ||
        options.historyWeight > 1.0) {
        return std::nullopt;
    }
    return options;
}

[[nodiscard]] std::filesystem::path gaussianSidecar(
    const std::filesystem::path& archive, std::uint64_t revision) {
    return archive.string() + ".gaussians.r" + std::to_string(revision) + ".bin";
}

[[nodiscard]] std::filesystem::path ownershipSidecar(
    const std::filesystem::path& archive, std::uint64_t revision) {
    return archive.string() + ".ownership.r" + std::to_string(revision) + ".bin";
}

[[nodiscard]] aether::Result<std::vector<std::byte>>
readBytes(const std::filesystem::path& path) {
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    constexpr std::uintmax_t maximumBytes = 32ULL * 1024ULL * 1024ULL * 1024ULL;
    if (error)
        return aether::fail(aether::ErrorCode::notFound,
                            "Unable to inspect CBRC sidecar", path.string());
    if (size == 0 || size > maximumBytes ||
        size > std::numeric_limits<std::size_t>::max()) {
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "CBRC sidecar size is invalid", path.string());
    }
    std::vector<std::byte> result(static_cast<std::size_t>(size));
    std::ifstream stream(path, std::ios::binary);
    stream.read(reinterpret_cast<char*>(result.data()),
                static_cast<std::streamsize>(result.size()));
    if (!stream)
        return aether::fail(aether::ErrorCode::io,
                            "Unable to read CBRC sidecar", path.string());
    return result;
}

[[nodiscard]] aether::Result<void>
atomicWrite(const std::filesystem::path& path, std::span<const std::byte> bytes) {
    if (bytes.empty())
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Cannot persist empty CBRC sidecar", path.string());
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        return aether::fail(aether::ErrorCode::io,
                            "Unable to write CBRC sidecar", path.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io,
                            "Unable to publish CBRC sidecar", error.message());
    }
    return {};
}

[[nodiscard]] bool writeText(const std::filesystem::path& path,
                             std::string_view text) {
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << text;
    stream.close();
    if (!stream)
        return false;
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return false;
    }
    return true;
}

[[nodiscard]] std::string jsonEscape(std::string_view value) {
    std::string result;
    result.reserve(value.size() + 8);
    for (const char ch : value) {
        if (ch == '\\' || ch == '"') {
            result.push_back('\\');
            result.push_back(ch);
        } else if (ch == '\n') {
            result += "\\n";
        } else {
            result.push_back(ch);
        }
    }
    return result;
}

[[nodiscard]] double sceneColorCap(const GaussianAsset& asset) {
    double cap = 1.0;
    for (const auto& primitive : asset.gaussians) {
        auto bound =
            aether::world_gaussian::gaussianRendererColorUpperBound(primitive);
        if (!bound)
            return std::numeric_limits<double>::quiet_NaN();
        for (const double channel : *bound)
            cap = std::max(cap, channel);
    }
    return cap;
}

[[nodiscard]] bool contains(const std::vector<aether::revision::RevisionNodeId>& values,
                            aether::revision::RevisionNodeId id) {
    return std::find(values.begin(), values.end(), id) != values.end();
}

struct SupportPlan final {
    bool empty{true};
    bool fullFrame{};
    std::uint64_t pixels{};
    std::array<double, 4> normalizedRect{};
};

[[nodiscard]] SupportPlan supportPlan(
    const aether::world_gaussian::GaussianImageRevisionCertificate& certificate) {
    SupportPlan result;
    std::size_t minX = certificate.width;
    std::size_t minY = certificate.height;
    std::size_t maxX{};
    std::size_t maxY{};
    bool any{};
    for (std::size_t y = 0; y < certificate.height; ++y) {
        for (std::size_t x = 0; x < certificate.width; ++x) {
            const auto index = y * certificate.width + x;
            if (certificate.rgbLInfBounds[index] <= 0.0)
                continue;
            any = true;
            minX = std::min(minX, x);
            minY = std::min(minY, y);
            maxX = std::max(maxX, x);
            maxY = std::max(maxY, y);
        }
    }
    if (!any)
        return result;

    result.empty = false;
    const std::size_t width = maxX - minX + 1;
    const std::size_t height = maxY - minY + 1;
    result.pixels = static_cast<std::uint64_t>(width) * height;
    result.fullFrame = result.pixels ==
        static_cast<std::uint64_t>(certificate.width) * certificate.height;
    result.normalizedRect = {
        static_cast<double>(minX) / certificate.width,
        static_cast<double>(minY) / certificate.height,
        static_cast<double>(maxX + 1) / certificate.width,
        static_cast<double>(maxY + 1) / certificate.height,
    };
    return result;
}

} // namespace

int main(int argc, char** argv) try {
    auto options = parseOptions(argc, argv);
    if (!options) {
        std::cerr << "Invalid CBRC revision arguments\n";
        return EXIT_FAILURE;
    }

    auto world = PersistentWorldModel::load(options->archive);
    if (!world) {
        std::cerr << world.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    const auto* beforeWorld = world->latest();
    if (!beforeWorld) {
        std::cerr << "World archive has no committed revision\n";
        return EXIT_FAILURE;
    }
    if (options->timestamp <= beforeWorld->timestamp) {
        std::cerr << "Timestamp must advance beyond current world revision\n";
        return EXIT_FAILURE;
    }
    const std::uint64_t previousRevision = beforeWorld->revision;

    auto gaussianBytes = readBytes(gaussianSidecar(options->archive, previousRevision));
    if (!gaussianBytes) {
        std::cerr << gaussianBytes.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto asset = aether::gaussian::GaussianCodec::decode(*gaussianBytes);
    if (!asset) {
        std::cerr << asset.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto ownershipBytes =
        readBytes(ownershipSidecar(options->archive, previousRevision));
    if (!ownershipBytes) {
        std::cerr << ownershipBytes.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto ownership =
        aether::world_gaussian::GaussianOwnershipCodec::decode(*ownershipBytes);
    if (!ownership) {
        std::cerr << ownership.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (ownership->owners.size() != asset->gaussians.size()) {
        std::cerr << "Gaussian/ownership sidecars disagree on cardinality\n";
        return EXIT_FAILURE;
    }

    std::vector<std::size_t> owned;
    for (std::size_t index = 0; index < ownership->owners.size(); ++index) {
        if (ownership->owners[index].value == options->entity)
            owned.push_back(index);
    }
    if (owned.empty()) {
        std::cerr << "Requested entity owns no Gaussian primitives\n";
        return EXIT_FAILURE;
    }

    GaussianAsset beforeChanged;
    beforeChanged.sphericalHarmonicDegree = asset->sphericalHarmonicDegree;
    beforeChanged.gaussians.reserve(owned.size());
    for (const std::size_t index : owned)
        beforeChanged.gaussians.push_back(asset->gaussians[index]);

    const double colorCap = sceneColorCap(*asset);
    if (!std::isfinite(colorCap)) {
        std::cerr << "Unable to construct conservative scene color cap\n";
        return EXIT_FAILURE;
    }

    auto overlay = GaussianOverlaySpatialIndex::build(
        *asset, aether::world::SelectiveUpdatePolicy{}.cellSizeMeters);
    if (!overlay) {
        std::cerr << overlay.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    auto edited =
        aether::world_gaussian::translatePersistentGaussianEntityIndexed(
            *world, *asset, *ownership, *overlay, EntityId{options->entity},
            options->target, options->timestamp);
    if (!edited) {
        std::cerr << edited.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    GaussianAsset afterChanged;
    afterChanged.sphericalHarmonicDegree = asset->sphericalHarmonicDegree;
    afterChanged.gaussians.reserve(owned.size());
    for (const std::size_t index : owned)
        afterChanged.gaussians.push_back(asset->gaussians[index]);

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

    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(
            beforeChanged, afterChanged, camera, colorCap);
    if (!certificate) {
        std::cerr << certificate.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    const auto support = supportPlan(*certificate);
    const std::uint64_t fullPixels =
        static_cast<std::uint64_t>(camera.width) * camera.height;

    const double localHistoryRepairWork =
        options->historyStable
            ? static_cast<double>(support.empty ? 0 : support.pixels)
            : static_cast<double>(fullPixels);
    const double fullHistoryRepairWork = static_cast<double>(fullPixels);
    auto plannerGraph = aether::revision::RevisionGraph::build(
        {
            {"exact-current-frame", 0.0, 0.0},
            {"temporal-history-repair", localHistoryRepairWork, 0.0},
        },
        {},
        fullHistoryRepairWork);
    if (!plannerGraph) {
        std::cerr << plannerGraph.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    std::vector<double> sourceBounds{
        0.0, certificate->maximumRgbLInfBound};
    std::vector<aether::revision::RevisionNodeId> hard{0};
    if (!options->historyStable)
        hard.push_back(1);
    const double historyWeight =
        options->historyStable ? options->historyWeight : 1.0;
    const std::vector<aether::revision::RevisionQoI> qois{
        {"resolved-rgb-linf", {{1, historyWeight}}, options->epsilon},
    };
    auto planned = aether::revision::greedyCertifiedRevisionCone(
        *plannerGraph, sourceBounds, hard, qois);
    if (!planned) {
        std::cerr << planned.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    const bool repairHistory = contains(planned->cone, 1);

    SupportPlan temporal;
    if (!options->historyStable) {
        temporal.empty = false;
        temporal.fullFrame = true;
        temporal.pixels = fullPixels;
        temporal.normalizedRect = {0.0, 0.0, 1.0, 1.0};
    } else if (repairHistory) {
        temporal = support;
    } else {
        temporal.empty = true;
        temporal.fullFrame = false;
        temporal.pixels = 0;
        temporal.normalizedRect = {};
    }

    const std::uint64_t revision = edited->worldEdit.candidate.revision;
    const auto afterGaussianPath = gaussianSidecar(options->archive, revision);
    const auto afterOwnershipPath = ownershipSidecar(options->archive, revision);
    auto encodedGaussians = aether::gaussian::GaussianCodec::encode(*asset);
    auto encodedOwnership =
        aether::world_gaussian::GaussianOwnershipCodec::encode(*ownership);
    if (!encodedGaussians || !encodedOwnership) {
        std::cerr << "Unable to encode persistent CBRC revision sidecars\n";
        return EXIT_FAILURE;
    }
    if (auto written = atomicWrite(afterGaussianPath, *encodedGaussians); !written) {
        std::cerr << written.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (auto written = atomicWrite(afterOwnershipPath, *encodedOwnership); !written) {
        std::cerr << written.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (auto saved = world->save(options->archive); !saved) {
        std::cerr << saved.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    std::error_code directoryError;
    std::filesystem::create_directories(options->outputDir, directoryError);
    if (directoryError) {
        std::cerr << "Unable to create output directory: "
                  << directoryError.message() << '\n';
        return EXIT_FAILURE;
    }

    const std::uint64_t touchedBytes =
        static_cast<std::uint64_t>(owned.size()) *
        aether::gaussian::GaussianCodec::recordBytes;
    const std::uint64_t fullPublicationBytes =
        static_cast<std::uint64_t>(asset->gaussians.size()) *
        aether::gaussian::GaussianCodec::recordBytes;

    std::ostringstream translation;
    translation << std::setprecision(17)
                << "{"
                << "\"schemaVersion\":1,"
                << "\"previousRevision\":" << previousRevision << ','
                << "\"revision\":" << revision << ','
                << "\"gaussianCount\":" << asset->gaussians.size() << ','
                << "\"beforeGaussianSidecar\":\""
                << jsonEscape(gaussianSidecar(options->archive, previousRevision).string())
                << "\","
                << "\"afterGaussianSidecar\":\""
                << jsonEscape(afterGaussianPath.string()) << "\","
                << "\"gaussianInputFormat\":\"aether-bin\","
                << "\"translatedGaussians\":" << edited->translatedGaussians << ','
                << "\"gaussiansInspected\":"
                << edited->reoptimizationSelection.inspectedGaussians << ','
                << "\"usedOverlayIndex\":"
                << (edited->usedOverlayIndex ? "true" : "false") << ','
                << "\"overlayIndexValid\":"
                << (edited->overlayIndexValid ? "true" : "false") << ','
                << "\"overlayIndexCompacted\":"
                << (edited->overlayIndexCompacted ? "true" : "false") << ','
                << "\"overlayDirtyRegionsQueried\":"
                << edited->overlayDiagnostics.dirtyRegionsQueried << ','
                << "\"overlayBaseEntriesVisited\":"
                << edited->overlayDiagnostics.baseEntriesVisited << ','
                << "\"overlayStaleBaseEntriesSkipped\":"
                << edited->overlayDiagnostics.staleBaseEntriesSkipped << ','
                << "\"overlayDeltaEntriesVisited\":"
                << edited->overlayDiagnostics.deltaEntriesVisited << ','
                << "\"reoptimizationGaussians\":"
                << edited->reoptimizationSelection.gaussianIndices.size() << ','
                << "\"protectedStableGaussians\":"
                << edited->reoptimizationSelection.rejectedStableOwnedGaussians << ','
                << "\"conservativeBoundaryGaussians\":"
                << edited->reoptimizationSelection.conservativeUnownedMatches << ','
                << "\"dirtyRegionCount\":"
                << edited->worldEdit.selectiveUpdate.dirtyRegions.size() << ','
                << "\"persisted\":true,"
                << "\"persistenceError\":\"\""
                << "}\n";

    const std::uint64_t affectedCount =
        static_cast<std::uint64_t>(std::count_if(
            certificate->rgbLInfBounds.begin(),
            certificate->rgbLInfBounds.end(),
            [](double value) { return value > 0.0; }));
    const double affectedRatio =
        fullPixels == 0
            ? 0.0
            : static_cast<double>(affectedCount) /
                  static_cast<double>(fullPixels);
    const double resolvedBound =
        planned->qois.empty()
            ? std::numeric_limits<double>::infinity()
            : planned->qois.front().bound;

    std::ostringstream cert;
    cert << std::setprecision(17)
         << "{"
         << "\"schemaVersion\":1,"
         << "\"available\":true,"
         << "\"revisionVersion\":" << revision << ','
         << "\"changedGaussians\":" << edited->translatedGaussians << ','
         << "\"affectedPixels\":" << affectedCount << ','
         << "\"fullFramePixels\":" << fullPixels << ','
         << "\"affectedPixelRatio\":" << affectedRatio << ','
         << "\"maximumCurrentRgbBound\":"
         << certificate->maximumRgbLInfBound << ','
         << "\"sceneColorUpperBound\":" << colorCap << ','
         << "\"camera\":{"
         << "\"width\":" << camera.width << ','
         << "\"height\":" << camera.height << ','
         << "\"focalX\":" << camera.focalX << ','
         << "\"focalY\":" << camera.focalY << ','
         << "\"centerX\":" << camera.centerX << ','
         << "\"centerY\":" << camera.centerY << ','
         << "\"near\":" << camera.nearPlane << ','
         << "\"far\":" << camera.farPlane << ','
         << "\"cameraWorldPosition\":["
         << camera.cameraWorldPosition[0] << ','
         << camera.cameraWorldPosition[1] << ','
         << camera.cameraWorldPosition[2] << "],"
         << "\"worldToCamera\":[";
    for (std::size_t i = 0; i < camera.worldToCamera.size(); ++i) {
        if (i)
            cert << ',';
        cert << camera.worldToCamera[i];
    }
    cert << "]},"
         << "\"invalidationCoversCertifiedSupport\":"
         << (repairHistory ? "true" : "false") << ','
         << "\"temporalFullFrameFallback\":"
         << (temporal.fullFrame ? "true" : "false") << ','
         << "\"outputConePlanner\":{"
         << "\"available\":true,"
         << "\"stable\":" << (planned->stable ? "true" : "false") << ','
         << "\"passes\":" << (planned->passes ? "true" : "false") << ','
         << "\"temporalRepairSelected\":"
         << (repairHistory ? "true" : "false") << ','
         << "\"fullRepair\":" << (planned->fullRebuild ? "true" : "false") << ','
         << "\"resolvedRgbBound\":" << resolvedBound << ','
         << "\"epsilon\":" << options->epsilon << ','
         << "\"plannerWork\":" << planned->work << ','
         << "\"fullWork\":" << planned->fullWork
         << "},"
         << "\"publication\":{"
         << "\"touchedRecords\":" << owned.size() << ','
         << "\"contiguousRanges\":0,"
         << "\"touchedBytes\":" << touchedBytes << ','
         << "\"fullBufferBytes\":" << fullPublicationBytes << ','
         << "\"byteRatio\":"
         << (fullPublicationBytes == 0
                 ? 0.0
                 : static_cast<double>(touchedBytes) /
                       static_cast<double>(fullPublicationBytes)) << ','
         << "\"frameSlotsQuiesced\":0,"
         << "\"globalTemporalHistoryInvalidated\":"
         << (temporal.fullFrame ? "true" : "false")
         << "},"
         << "\"temporal\":{"
         << "\"fullFrame\":" << (temporal.fullFrame ? "true" : "false") << ','
         << "\"empty\":" << (temporal.empty ? "true" : "false") << ','
         << "\"invalidatedPixels\":" << temporal.pixels << ','
         << "\"fullFramePixels\":" << fullPixels << ','
         << "\"pixelRatio\":"
         << (fullPixels == 0
                 ? 0.0
                 : static_cast<double>(temporal.pixels) /
                       static_cast<double>(fullPixels)) << ','
         << "\"normalizedRect\":["
         << temporal.normalizedRect[0] << ','
         << temporal.normalizedRect[1] << ','
         << temporal.normalizedRect[2] << ','
         << temporal.normalizedRect[3] << "]"
         << "},"
         << "\"evidenceMode\":\"headless-reference-certificate\""
         << "}\n";

    const auto translationPath = options->outputDir / "translation.json";
    const auto certificatePath = options->outputDir / "certificate.json";
    if (!writeText(translationPath, translation.str()) ||
        !writeText(certificatePath, cert.str())) {
        std::cerr << "Unable to publish CBRC evidence JSON\n";
        return EXIT_FAILURE;
    }

    std::cout << "{\"translation\":\""
              << jsonEscape(translationPath.string())
              << "\",\"certificate\":\""
              << jsonEscape(certificatePath.string())
              << "\",\"revision\":" << revision
              << ",\"temporalRepairSelected\":"
              << (repairHistory ? "true" : "false")
              << "}\n";
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "CBRC revision exception: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "CBRC revision unknown exception\n";
    return EXIT_FAILURE;
}
