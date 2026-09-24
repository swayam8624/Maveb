#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>
#include <aether/world_gaussian/GaussianRenderCertificate.hpp>
#if defined(__APPLE__) && defined(AETHER_ORACLE_METAL_ENABLED)
#include <aether/metal/GaussianPipeline.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <Foundation/Foundation.hpp>
#include <Metal/Metal.hpp>
#endif

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
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::gaussian::ReferenceCamera;
using aether::gaussian::ReferenceImage;
using Pixel = std::array<float, 4>;
using Pixels = std::vector<Pixel>;
using Path = std::filesystem::path;
using WriteResult = aether::Result<void>;

struct ImageExtent final {
    std::size_t width{};
    std::size_t height{};
};

struct Options final {
    std::string beforePath;
    std::string afterPath;
    std::string changedCsv;
    std::string inputFormat{"ply"};
    std::string spatialOutputPath;
    std::string visualOutputDir;
    std::string backend{"auto"};
    bool detectChanged{};
    bool verifyMetalParity{};
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
        1.0F, 0.0F, 0.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F,
        0.0F, 0.0F, 1.0F, 0.0F, 0.0F, 0.0F, 0.0F, 1.0F,
    };
    double epsilon{0.01};
    double repairOmitFraction{};
};


#if defined(__APPLE__) && defined(AETHER_ORACLE_METAL_ENABLED)
[[nodiscard]] std::uint32_t metalEntryBudget(std::size_t gaussianCount) {
    constexpr std::uint64_t maximum = 4'194'304;
    const std::uint64_t requested =
        gaussianCount > maximum / 64 ? maximum : static_cast<std::uint64_t>(gaussianCount) * 64;
    return static_cast<std::uint32_t>(
        std::clamp<std::uint64_t>(requested, 262'144, maximum));
}

[[nodiscard]] aether::metal::MetalPtr<MTL::Texture>
makeMetalTarget(MTL::Device* device, MTL::PixelFormat format, std::size_t width,
                std::size_t height) {
    auto descriptor = aether::metal::adopt(MTL::TextureDescriptor::alloc()->init());
    descriptor->setTextureType(MTL::TextureType2D);
    descriptor->setPixelFormat(format);
    descriptor->setWidth(width);
    descriptor->setHeight(height);
    descriptor->setStorageMode(MTL::StorageModeShared);
    descriptor->setUsage(MTL::TextureUsageShaderWrite | MTL::TextureUsageShaderRead);
    return aether::metal::adopt(device->newTexture(descriptor.get()));
}

[[nodiscard]] std::optional<ReferenceImage>
renderMetalReference(const GaussianAsset& asset, const ReferenceCamera& camera,
                     std::array<float, 3> background, std::string& error) {
    struct PoolGuard final {
        NS::AutoreleasePool* pool{NS::AutoreleasePool::alloc()->init()};
        ~PoolGuard() {
            if (pool)
                pool->release();
        }
    } poolGuard;

    auto device = aether::metal::adopt(MTL::CreateSystemDefaultDevice());
    if (!device) {
        error = "No Metal device is available";
        return std::nullopt;
    }
    NS::Error* libraryError = nullptr;
    auto library = aether::metal::adopt(device->newLibrary(
        NS::String::string(AETHER_ORACLE_SHADER_LIBRARY, NS::UTF8StringEncoding),
        &libraryError));
    if (!library) {
        error = libraryError ? libraryError->localizedDescription()->utf8String()
                             : "Unable to load CBRC oracle metallib";
        return std::nullopt;
    }
    auto pipelineResult = aether::metal::GaussianPipeline::create(
        device.get(), library.get(), metalEntryBudget(asset.gaussians.size()));
    if (!pipelineResult) {
        error = pipelineResult.error().describe();
        return std::nullopt;
    }
    auto pipeline = std::move(*pipelineResult);
    if (auto loaded = pipeline->load(asset); !loaded) {
        error = loaded.error().describe();
        return std::nullopt;
    }

    auto color = makeMetalTarget(device.get(), MTL::PixelFormatRGBA32Float, camera.width,
                                 camera.height);
    auto depth = makeMetalTarget(device.get(), MTL::PixelFormatR32Float, camera.width,
                                 camera.height);
    auto ids = makeMetalTarget(device.get(), MTL::PixelFormatR32Uint, camera.width,
                               camera.height);
    auto queue = aether::metal::adopt(device->newCommandQueue());
    if (!color || !depth || !ids || !queue) {
        error = "Unable to allocate shared Metal oracle targets";
        return std::nullopt;
    }

    AetherGaussianCamera gpuCamera{};
    gpuCamera.worldToCamera.columns[0] = {
        camera.worldToCamera[0], camera.worldToCamera[4],
        camera.worldToCamera[8], camera.worldToCamera[12]};
    gpuCamera.worldToCamera.columns[1] = {
        camera.worldToCamera[1], camera.worldToCamera[5],
        camera.worldToCamera[9], camera.worldToCamera[13]};
    gpuCamera.worldToCamera.columns[2] = {
        camera.worldToCamera[2], camera.worldToCamera[6],
        camera.worldToCamera[10], camera.worldToCamera[14]};
    gpuCamera.worldToCamera.columns[3] = {
        camera.worldToCamera[3], camera.worldToCamera[7],
        camera.worldToCamera[11], camera.worldToCamera[15]};
    gpuCamera.focalCenter = {camera.focalX, camera.focalY, camera.centerX, camera.centerY};
    gpuCamera.depthViewport = {camera.nearPlane, camera.farPlane,
                               static_cast<float>(camera.width),
                               static_cast<float>(camera.height)};
    gpuCamera.cameraWorldPosition = {
        camera.cameraWorldPosition[0], camera.cameraWorldPosition[1],
        camera.cameraWorldPosition[2], 1.0F};

    MTL::CommandBuffer* commandBuffer = queue->commandBuffer();
    if (!commandBuffer) {
        error = "Unable to allocate Metal oracle command buffer";
        return std::nullopt;
    }
    if (auto encoded = pipeline->encode(commandBuffer, gpuCamera, color.get(), depth.get(),
                                        ids.get(), 0);
        !encoded) {
        error = encoded.error().describe();
        return std::nullopt;
    }
    commandBuffer->commit();
    commandBuffer->waitUntilCompleted();
    if (commandBuffer->status() == MTL::CommandBufferStatusError) {
        error = "Metal oracle command buffer failed";
        return std::nullopt;
    }
    if (pipeline->statistics().overflowedEntries != 0) {
        error = "Metal oracle tile-entry budget overflowed";
        return std::nullopt;
    }

    ReferenceImage image;
    image.width = camera.width;
    image.height = camera.height;
    const std::size_t pixelCount = camera.width * camera.height;
    image.color.resize(pixelCount);
    image.depth.resize(pixelCount);
    image.ids.resize(pixelCount);
    const MTL::Region region = MTL::Region::Make2D(0, 0, camera.width, camera.height);
    color->getBytes(image.color.data(), camera.width * sizeof(Pixel), region, 0);
    depth->getBytes(image.depth.data(), camera.width * sizeof(float), region, 0);
    ids->getBytes(image.ids.data(), camera.width * sizeof(std::uint32_t), region, 0);
    for (auto& pixel : image.color) {
        for (std::size_t channel = 0; channel < 3; ++channel)
            pixel[channel] +=
                (1.0F - pixel[3]) * std::clamp(background[channel], 0.0F, 1.0F);
    }
    return image;
}
#endif

[[nodiscard]] bool verifyImageParity(const ReferenceImage& accelerated,
                                     const ReferenceImage& reference,
                                     double rgbTolerance, double depthTolerance,
                                     std::string& reason) {
    if (accelerated.width != reference.width || accelerated.height != reference.height ||
        accelerated.color.size() != reference.color.size() ||
        accelerated.depth.size() != reference.depth.size() ||
        accelerated.ids.size() != reference.ids.size()) {
        reason = "Metal/CPU image extent mismatch";
        return false;
    }
    double maximumRgb{};
    double maximumDepth{};
    std::size_t idMismatches{};
    for (std::size_t pixel = 0; pixel < reference.color.size(); ++pixel) {
        for (std::size_t channel = 0; channel < 4; ++channel) {
            maximumRgb = std::max(
                maximumRgb,
                std::abs(static_cast<double>(accelerated.color[pixel][channel]) -
                         static_cast<double>(reference.color[pixel][channel])));
        }
        const float acceleratedDepth = accelerated.depth[pixel];
        const float referenceDepth = reference.depth[pixel];
        if (std::isfinite(acceleratedDepth) || std::isfinite(referenceDepth)) {
            if (!(std::isfinite(acceleratedDepth) && std::isfinite(referenceDepth))) {
                maximumDepth = std::numeric_limits<double>::infinity();
            } else {
                maximumDepth = std::max(
                    maximumDepth,
                    std::abs(static_cast<double>(acceleratedDepth) -
                             static_cast<double>(referenceDepth)));
            }
        }
        idMismatches += static_cast<std::size_t>(
            accelerated.ids[pixel] != reference.ids[pixel]);
    }
    if (maximumRgb > rgbTolerance || maximumDepth > depthTolerance || idMismatches != 0) {
        std::ostringstream stream;
        stream << "Metal/CPU oracle parity failed: max RGB=" << maximumRgb
               << ", max depth=" << maximumDepth << ", ID mismatches=" << idMismatches;
        reason = stream.str();
        return false;
    }
    return true;
}

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
[[nodiscard]] std::optional<std::array<float, N>> parseFloatCsv(std::string_view csv) {
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
    if (const char* backend = std::getenv("MAVEB_ORACLE_BACKEND"); backend && *backend)
        options.backend = backend;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        const auto requireValue = [&](std::string_view name) -> std::optional<std::string_view> {
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
        } else if (arg == "--input-format") {
            auto value = requireValue(arg);
            if (!value || (*value != "ply" && *value != "aether-bin"))
                return std::nullopt;
            options.inputFormat = *value;
        } else if (arg == "--backend") {
            auto value = requireValue(arg);
            if (!value || (*value != "auto" && *value != "cpu" && *value != "metal"))
                return std::nullopt;
            options.backend = *value;
        } else if (arg == "--verify-metal-parity") {
            options.verifyMetalParity = true;
        } else if (arg == "--changed") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.changedCsv = *value;
        } else if (arg == "--detect-changed") {
            options.detectChanged = true;
        } else if (arg == "--spatial-output") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.spatialOutputPath = *value;
        } else if (arg == "--visual-output-dir") {
            auto value = requireValue(arg);
            if (!value)
                return std::nullopt;
            options.visualOutputDir = *value;
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
        } else if (arg == "--focal-x" || arg == "--focal-y" || arg == "--center-x" ||
                   arg == "--center-y" || arg == "--near" || arg == "--far" || arg == "--epsilon" ||
                   arg == "--repair-omit-fraction" || arg == "--background-r" ||
                   arg == "--background-g" || arg == "--background-b") {
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
            else if (arg == "--repair-omit-fraction")
                options.repairOmitFraction = *parsed;
            else if (arg == "--background-r")
                options.background[0] = static_cast<float>(*parsed);
            else if (arg == "--background-g")
                options.background[1] = static_cast<float>(*parsed);
            else
                options.background[2] = static_cast<float>(*parsed);
        } else if (arg == "--help") {
            std::cout << "Usage: maveb-cbrc-gaussian-oracle --before OLD.ply --after NEW.ply "
                         "(--changed 1,4,9 | --detect-changed) [camera options]\n"
                      << "  --input-format ply|aether-bin (default: ply)\n"
                      << "  --backend auto|cpu|metal (default: auto; env MAVEB_ORACLE_BACKEND)\n"
                      << "  --verify-metal-parity compares Metal output with the scalar CPU oracle\n"
                      << "  --detect-changed compares stable source-order before/after records\n"
                      << "  --spatial-output FILE.csv writes per-pixel actual,bound evidence\n"
                      << "  --visual-output-dir DIR writes before/after/repair/heatmap PPMs\n"
                      << "  --width N --height N --focal-x F --focal-y F\n"
                      << "  --center-x F --center-y F --near F --far F\n"
                      << "  --world-to-camera m00,m01,...,m33 (row-major)\n"
                      << "  --camera-world-position x,y,z\n"
                      << "  --background-r F --background-g F --background-b F\n"
                      << "  --epsilon F\n"
                      << "  --repair-omit-fraction F leaves a deterministic fraction of changed "
                         "Gaussians stale and certifies that omitted subset (reviewer probe)\n";
            std::exit(EXIT_SUCCESS);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            return std::nullopt;
        }
    }

    const bool hasExplicitChanged = !options.changedCsv.empty();
    if (options.beforePath.empty() || options.afterPath.empty() ||
        hasExplicitChanged == options.detectChanged || options.epsilon < 0.0 ||
        options.repairOmitFraction < 0.0 || options.repairOmitFraction >= 1.0 ||
        options.focalX <= 0.0F || options.focalY <= 0.0F || options.nearPlane <= 0.0F ||
        options.farPlane <= options.nearPlane ||
        (options.backend != "auto" && options.backend != "cpu" && options.backend != "metal"))
        return std::nullopt;
    return options;
}

[[nodiscard]] std::optional<std::vector<std::size_t>> parseChangedIndices(std::string_view csv) {
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

[[nodiscard]] aether::Result<GaussianAsset> loadGaussianState(const std::string& path,
                                                              std::string_view format) {
    if (format == "ply")
        return aether::gaussian::PlyLoader::load(path);
    if (format != "aether-bin")
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Unsupported Gaussian oracle input format", std::string(format));

    std::error_code filesystemError;
    const auto fileBytes = std::filesystem::file_size(path, filesystemError);
    constexpr std::uintmax_t maximumBytes = 32ULL * 1024ULL * 1024ULL * 1024ULL;
    if (filesystemError)
        return aether::fail(aether::ErrorCode::notFound,
                            "Unable to inspect canonical Gaussian sidecar", path);
    if (fileBytes == 0 || fileBytes > maximumBytes ||
        fileBytes > std::numeric_limits<std::size_t>::max()) {
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Canonical Gaussian sidecar size is invalid", path);
    }

    std::vector<std::byte> bytes(static_cast<std::size_t>(fileBytes));
    std::ifstream stream(path, std::ios::binary);
    stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!stream)
        return aether::fail(aether::ErrorCode::io, "Unable to read canonical Gaussian sidecar",
                            path);
    auto decoded = aether::gaussian::GaussianCodec::decode(bytes);
    if (decoded)
        decoded->name = std::filesystem::path(path).stem().string();
    return decoded;
}

[[nodiscard]] bool sameGaussian(const Gaussian& a, const Gaussian& b) noexcept {
    return a.position == b.position && a.logScale == b.logScale && a.rotation == b.rotation &&
           a.opacityLogit == b.opacityLogit && a.dc == b.dc && a.rest == b.rest &&
           a.restCount == b.restCount;
}

[[nodiscard]] double sceneColorCap(const GaussianAsset& before, const GaussianAsset& after) {
    double cap = 1.0; // reference background is clamped to [0,1].
    const auto accumulate = [&](const GaussianAsset& asset) -> bool {
        for (const Gaussian& primitive : asset.gaussians) {
            auto bound = aether::world_gaussian::gaussianRendererColorUpperBound(primitive);
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

[[nodiscard]] unsigned char toByte(double value) {
    const double clamped = std::clamp(value, 0.0, 1.0);
    return static_cast<unsigned char>(std::lround(clamped * 255.0));
}

[[nodiscard]] WriteResult writePpm(const Path& path, ImageExtent extent, const Pixels& colors) {
    if (colors.size() != extent.width * extent.height)
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "PPM color cardinality does not match image dimensions");
    std::error_code error;
    if (!path.parent_path().empty())
        std::filesystem::create_directories(path.parent_path(), error);
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to create visual output directory",
                            error.message());
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream << "P6\n" << extent.width << ' ' << extent.height << "\n255\n";
    for (const Pixel& color : colors) {
        const std::array<unsigned char, 3> bytes{
            toByte(color[0]),
            toByte(color[1]),
            toByte(color[2]),
        };
        stream.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    }
    stream.close();
    if (!stream)
        return aether::fail(aether::ErrorCode::io, "Unable to write PPM", path.string());
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to publish PPM", error.message());
    }
    return {};
}

[[nodiscard]] Pixel heatColor(double value, double maximum) {
    const double t = maximum <= 0.0 ? 0.0 : std::clamp(value / maximum, 0.0, 1.0);
    // Perceptually ordered dark-blue -> cyan -> yellow -> white ramp.
    const double r = std::clamp(2.2 * t - 0.35, 0.0, 1.0);
    const double g = std::clamp(2.0 * t, 0.0, 1.0);
    const double b = std::clamp(1.4 - 1.6 * t, 0.0, 1.0);
    return {static_cast<float>(r), static_cast<float>(g), static_cast<float>(b), 1.0F};
}

} // namespace

int main(int argc, char** argv) try {
    auto options = parseOptions(argc, argv);
    if (!options) {
        std::cerr << "Invalid CBRC Gaussian oracle arguments\n";
        return EXIT_FAILURE;
    }
    std::optional<std::vector<std::size_t>> changed;
    if (!options->detectChanged) {
        changed = parseChangedIndices(options->changedCsv);
        if (!changed) {
            std::cerr << "Invalid --changed list; indices must be unique non-negative integers\n";
            return EXIT_FAILURE;
        }
    }

    auto before = loadGaussianState(options->beforePath, options->inputFormat);
    if (!before) {
        std::cerr << before.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    auto after = loadGaussianState(options->afterPath, options->inputFormat);
    if (!after) {
        std::cerr << after.error().describe() << '\n';
        return EXIT_FAILURE;
    }
    if (before->gaussians.size() != after->gaussians.size()) {
        std::cerr << "Oracle currently requires stable source-order Gaussian count\n";
        return EXIT_FAILURE;
    }

    if (options->detectChanged) {
        std::vector<std::size_t> detected;
        detected.reserve(before->gaussians.size() / 100 + 1);
        for (std::size_t index = 0; index < before->gaussians.size(); ++index) {
            if (!sameGaussian(before->gaussians[index], after->gaussians[index]))
                detected.push_back(index);
        }
        if (detected.empty()) {
            std::cerr << "Auto-diff found no changed Gaussian records\n";
            return EXIT_FAILURE;
        }
        changed = std::move(detected);
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

    std::vector<bool> isOmitted(before->gaussians.size(), false);
    std::size_t omittedCount{};
    if (options->repairOmitFraction > 0.0 && changed->size() >= 2) {
        omittedCount = static_cast<std::size_t>(
            std::floor(options->repairOmitFraction * static_cast<double>(changed->size())));
        omittedCount = std::max<std::size_t>(1, omittedCount);
        omittedCount = std::min<std::size_t>(changed->size() - 1, omittedCount);
        for (std::size_t k = 0; k < omittedCount; ++k) {
            const std::size_t changedPosition = std::min<std::size_t>(
                changed->size() - 1, ((k + 1) * changed->size()) / (omittedCount + 1));
            isOmitted[(*changed)[changedPosition]] = true;
        }
        omittedCount =
            static_cast<std::size_t>(std::count(isOmitted.begin(), isOmitted.end(), true));
    }

    GaussianAsset omittedBefore;
    GaussianAsset omittedAfter;
    omittedBefore.name = "before-omitted";
    omittedAfter.name = "after-omitted";
    omittedBefore.sphericalHarmonicDegree = before->sphericalHarmonicDegree;
    omittedAfter.sphericalHarmonicDegree = after->sphericalHarmonicDegree;
    omittedBefore.gaussians.reserve(omittedCount);
    omittedAfter.gaussians.reserve(omittedCount);

    GaussianAsset repairedState = *after;
    repairedState.name = "selected-partial-repair";
    if (omittedCount > 0) {
        for (const std::size_t index : *changed) {
            if (!isOmitted[index])
                continue;
            omittedBefore.gaussians.push_back(before->gaussians[index]);
            omittedAfter.gaussians.push_back(after->gaussians[index]);
            repairedState.gaussians[index] = before->gaussians[index];
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

    std::optional<ReferenceImage> oldImage;
    std::optional<ReferenceImage> newImage;
    std::optional<ReferenceImage> repairImage;
    std::string renderBackend = "cpu";

    const auto renderCpu = [&](const GaussianAsset& asset) -> std::optional<ReferenceImage> {
        auto rendered =
            aether::gaussian::ReferenceRasterizer::render(asset, camera, options->background);
        if (!rendered) {
            std::cerr << rendered.error().describe() << '\n';
            return std::nullopt;
        }
        return std::move(*rendered);
    };

    const bool wantsMetal = options->backend == "metal" || options->backend == "auto";
#if defined(__APPLE__) && defined(AETHER_ORACLE_METAL_ENABLED)
    if (wantsMetal) {
        std::string metalError;
        oldImage = renderMetalReference(*before, camera, options->background, metalError);
        if (oldImage)
            newImage = renderMetalReference(*after, camera, options->background, metalError);
        if (newImage)
            repairImage =
                renderMetalReference(repairedState, camera, options->background, metalError);
        if (oldImage && newImage && repairImage) {
            renderBackend = "metal";
        } else {
            oldImage.reset();
            newImage.reset();
            repairImage.reset();
            if (options->backend == "metal") {
                std::cerr << "Strict Metal oracle failed: " << metalError << '\n';
                return EXIT_FAILURE;
            }
            std::cerr << "Metal oracle unavailable; falling back to CPU reference: "
                      << metalError << '\n';
        }
    }
#else
    if (options->backend == "metal") {
        std::cerr << "Strict Metal oracle requested but this build has no Metal backend\n";
        return EXIT_FAILURE;
    }
#endif

    if (!oldImage) {
        oldImage = renderCpu(*before);
        newImage = renderCpu(*after);
        repairImage = renderCpu(repairedState);
        renderBackend = "cpu";
    }
    if (!oldImage || !newImage || !repairImage)
        return EXIT_FAILURE;

    if (options->verifyMetalParity) {
        if (renderBackend != "metal") {
            std::cerr << "--verify-metal-parity requires an available Metal backend\n";
            return EXIT_FAILURE;
        }
        auto cpuOld = renderCpu(*before);
        auto cpuNew = renderCpu(*after);
        auto cpuRepair = renderCpu(repairedState);
        if (!cpuOld || !cpuNew || !cpuRepair)
            return EXIT_FAILURE;
        std::string parityReason;
        constexpr double kRgbParityTolerance = 5.0e-4;
        constexpr double kDepthParityTolerance = 1.0e-4;
        if (!verifyImageParity(*oldImage, *cpuOld, kRgbParityTolerance,
                               kDepthParityTolerance, parityReason) ||
            !verifyImageParity(*newImage, *cpuNew, kRgbParityTolerance,
                               kDepthParityTolerance, parityReason) ||
            !verifyImageParity(*repairImage, *cpuRepair, kRgbParityTolerance,
                               kDepthParityTolerance, parityReason)) {
            std::cerr << parityReason << '\n';
            return EXIT_FAILURE;
        }
    }

    const double colorCap = sceneColorCap(*before, *after);
    if (!std::isfinite(colorCap)) {
        std::cerr << "Unable to construct conservative scene color cap\n";
        return EXIT_FAILURE;
    }
    auto certificate = aether::world_gaussian::certifyGaussianImageRevision(
        beforeChanged, afterChanged, camera, colorCap);
    if (!certificate) {
        std::cerr << certificate.error().describe() << '\n';
        return EXIT_FAILURE;
    }

    std::vector<double> repairBounds(oldImage->color.size(), 0.0);
    if (omittedCount > 0) {
        auto repairCertificate = aether::world_gaussian::certifyGaussianImageRevision(
            omittedBefore, omittedAfter, camera, colorCap);
        if (!repairCertificate) {
            std::cerr << repairCertificate.error().describe() << '\n';
            return EXIT_FAILURE;
        }
        repairBounds = repairCertificate->rgbLInfBounds;
        if (repairBounds.size() != oldImage->color.size()) {
            std::cerr << "Partial-repair certificate pixel cardinality mismatch\n";
            return EXIT_FAILURE;
        }
    }

    constexpr double kOracleNumericalSlack = 2.0e-6;
    double maximumActual{};
    double maximumBound{};
    double maximumRepairResidual{};
    double maximumRepairResidualBound{};
    std::size_t affectedPixels{};
    std::size_t certificateViolations{};
    std::size_t repairCertificateViolations{};
    std::size_t toleranceViolations{};
    std::vector<double> actualResiduals;
    std::vector<double> repairResiduals;
    if (!options->spatialOutputPath.empty()) {
        actualResiduals.resize(oldImage->color.size());
    }
    if (!options->spatialOutputPath.empty() || !options->visualOutputDir.empty()) {
        repairResiduals.resize(oldImage->color.size());
    }

    for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual =
                std::max(actual, std::abs(static_cast<double>(oldImage->color[pixel][channel]) -
                                          static_cast<double>(newImage->color[pixel][channel])));
        }
        const double bound = certificate->rgbLInfBounds[pixel];
        const bool repairedPixel = bound > 0.0;
        double repairResidual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            const double repairedChannel = static_cast<double>(repairImage->color[pixel][channel]);
            const double fullChannel = static_cast<double>(newImage->color[pixel][channel]);
            repairResidual = std::max(repairResidual, std::abs(repairedChannel - fullChannel));
        }
        const double repairBound = repairBounds[pixel];
        if (!actualResiduals.empty())
            actualResiduals[pixel] = actual;
        if (!repairResiduals.empty())
            repairResiduals[pixel] = repairResidual;
        maximumActual = std::max(maximumActual, actual);
        maximumBound = std::max(maximumBound, bound);
        maximumRepairResidual = std::max(maximumRepairResidual, repairResidual);
        maximumRepairResidualBound = std::max(maximumRepairResidualBound, repairBound);
        affectedPixels += static_cast<std::size_t>(repairedPixel);
        const bool certificateViolation = actual > bound + kOracleNumericalSlack;
        certificateViolations += static_cast<std::size_t>(certificateViolation);
        const bool repairCertificateViolation =
            repairResidual > repairBound + kOracleNumericalSlack;
        repairCertificateViolations += static_cast<std::size_t>(repairCertificateViolation);
        const bool outsideTolerance = actual > options->epsilon + kOracleNumericalSlack;
        toleranceViolations += static_cast<std::size_t>(outsideTolerance);
    }

    if (!options->spatialOutputPath.empty()) {
        const std::filesystem::path outputPath = options->spatialOutputPath;
        if (!outputPath.parent_path().empty()) {
            std::error_code directoryError;
            std::filesystem::create_directories(outputPath.parent_path(), directoryError);
            if (directoryError) {
                std::cerr << "Unable to create spatial evidence directory: "
                          << directoryError.message() << '\n';
                return EXIT_FAILURE;
            }
        }
        const std::filesystem::path temporary = outputPath.string() + ".tmp";
        std::ofstream spatial(temporary, std::ios::trunc);
        if (!spatial) {
            std::cerr << "Unable to open spatial evidence output\n";
            return EXIT_FAILURE;
        }
        spatial << "x,y,actual_rgb_linf,certified_bound,post_repair_residual_rgb_linf,"
                   "post_repair_certified_bound,certificate_violation,"
                   "post_repair_certificate_violation\n";
        spatial << std::setprecision(17);
        for (std::size_t pixel = 0; pixel < actualResiduals.size(); ++pixel) {
            const std::size_t x = pixel % camera.width;
            const std::size_t y = pixel / camera.width;
            const double actual = actualResiduals[pixel];
            const double bound = certificate->rgbLInfBounds[pixel];
            const double repairResidual = repairResiduals[pixel];
            const double repairBound = repairBounds[pixel];
            spatial << x << ',' << y << ',' << actual << ',' << bound << ',';
            spatial << repairResidual << ',' << repairBound << ',';
            spatial << (actual > bound + kOracleNumericalSlack ? 1 : 0) << ',';
            spatial << (repairResidual > repairBound + kOracleNumericalSlack ? 1 : 0) << '\n';
        }
        spatial.close();
        if (!spatial) {
            std::cerr << "Unable to write spatial evidence output\n";
            std::error_code ignored;
            std::filesystem::remove(temporary, ignored);
            return EXIT_FAILURE;
        }
        std::error_code publishError;
        std::filesystem::rename(temporary, outputPath, publishError);
        if (publishError) {
            std::cerr << "Unable to publish spatial evidence output: " << publishError.message()
                      << '\n';
            std::filesystem::remove(temporary, publishError);
            return EXIT_FAILURE;
        }
    }

    if (!options->visualOutputDir.empty()) {
        const std::filesystem::path visualRoot = options->visualOutputDir;
        Pixels selectedRepairPixels(oldImage->color.size());
        Pixels supportHeat(oldImage->color.size());
        Pixels effectHeat(oldImage->color.size());
        Pixels residualHeat(oldImage->color.size());
        for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
            const double bound = certificate->rgbLInfBounds[pixel];
            const double residualBound = repairBounds[pixel];
            selectedRepairPixels[pixel] = repairImage->color[pixel];
            const double supportValue = options->repairOmitFraction > 0.0 ? residualBound : bound;
            const double supportMaximum = options->repairOmitFraction > 0.0
                                              ? std::max(maximumRepairResidualBound, 1.0e-12)
                                              : maximumBound;
            supportHeat[pixel] = heatColor(supportValue, supportMaximum);
            double actual{};
            for (std::size_t channel = 0; channel < 3; ++channel) {
                const double beforeChannel = oldImage->color[pixel][channel];
                const double afterChannel = newImage->color[pixel][channel];
                actual = std::max(actual, std::abs(beforeChannel - afterChannel));
            }
            const double residual = repairResiduals[pixel];
            effectHeat[pixel] = heatColor(actual, maximumActual);
            residualHeat[pixel] = heatColor(residual, std::max(maximumRepairResidual, 1.0e-12));
        }

        const std::array<std::pair<std::string_view, const Pixels*>, 6> images{{
            {"before.ppm", &oldImage->color},
            {"full-after.ppm", &newImage->color},
            {"selected-repair.ppm", &selectedRepairPixels},
            {"certified-support.ppm", &supportHeat},
            {"edit-effect.ppm", &effectHeat},
            {"post-repair-residual.ppm", &residualHeat},
        }};
        for (const auto& [name, colors] : images) {
            const ImageExtent extent{camera.width, camera.height};
            if (auto written = writePpm(visualRoot / name, extent, *colors); !written) {
                std::cerr << written.error().describe() << '\n';
                return EXIT_FAILURE;
            }
        }
    }

    const double effectivity = maximumBound / std::max(maximumActual, 1.0e-15);
    const double affectedFraction =
        static_cast<double>(affectedPixels) / static_cast<double>(oldImage->color.size());
    const bool withinTolerance = maximumBound <= options->epsilon;
    const bool certified = certificateViolations == 0;
    const double repairResidualBound = maximumRepairResidualBound + kOracleNumericalSlack;
    const bool repairResidualCertified = repairCertificateViolations == 0;
    const bool repairWithinTolerance =
        repairResidualCertified && repairResidualBound <= options->epsilon;

    std::cout << std::setprecision(17) << "{"
              << "\"schemaVersion\":1,"
              << "\"experiment\":\"cbrc-gaussian-full-reference-oracle-v1\","
              << "\"method\":\"CBRC\","
              << "\"renderBackend\":\"" << renderBackend << "\","
              << "\"totalGaussians\":" << before->gaussians.size() << ','
              << "\"changedGaussians\":" << changed->size() << ',' << "\"changedFraction\":"
              << static_cast<double>(changed->size()) /
                     static_cast<double>(before->gaussians.size())
              << ',' << "\"affectedPixels\":" << affectedPixels << ','
              << "\"affectedPixelFraction\":" << affectedFraction << ','
              << "\"spatialEvidenceWritten\":"
              << (!options->spatialOutputPath.empty() ? "true" : "false") << ','
              << "\"visualEvidenceWritten\":"
              << (!options->visualOutputDir.empty() ? "true" : "false") << ','
              << "\"colorUpperBound\":" << colorCap << ',' << "\"qois\":{\"rgb_linf\":{"
              << "\"epsilon\":" << options->epsilon << ',' << "\"certified_bound\":" << maximumBound
              << ',' << "\"measured_full_reference_error\":" << maximumActual << "}},"
              << "\"repair_qois\":{\"rgb_linf\":{\"epsilon\":" << options->epsilon << ','
              << "\"certified_bound\":" << repairResidualBound << ','
              << "\"measured_full_reference_error\":" << maximumRepairResidual << "}},"
              << "\"effectivity\":" << effectivity << ',' << "\"repairMode\":\""
              << (options->repairOmitFraction > 0.0 ? "certified-omitted-gaussians-v1"
                                                    : "exact-changed-support-v1")
              << "\","
              << "\"repairOmitFractionRequested\":" << options->repairOmitFraction << ','
              << "\"repairOmittedGaussians\":" << omittedCount << ','
              << "\"repairAppliedChangedGaussians\":" << (changed->size() - omittedCount) << ','
              << "\"certificateViolationPixels\":" << certificateViolations << ','
              << "\"repairCertificateViolationPixels\":" << repairCertificateViolations << ','
              << "\"toleranceViolationPixels\":" << toleranceViolations << ','
              << "\"certified\":" << (certified ? "true" : "false") << ','
              << "\"withinTolerance\":" << (withinTolerance ? "true" : "false") << ','
              << "\"repairWithinTolerance\":" << (repairWithinTolerance ? "true" : "false")
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
