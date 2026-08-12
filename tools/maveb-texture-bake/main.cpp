#include <aether/hybrid/ProxyPlyLoader.hpp>
#include <aether/mesh/GltfExporter.hpp>
#include <aether/mesh/GltfLoader.hpp>
#include <aether/package/Sha256.hpp>
#include <aether/reconstruction/TextureBaker.hpp>

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <simdjson.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <limits>
#include <locale>
#include <numeric>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

using aether::reconstruction::TextureBakeCamera;
using aether::reconstruction::TextureBakeConfig;
using aether::reconstruction::TextureBakeImage;
using aether::reconstruction::TextureCameraModel;

template <typename Type> class CfOwner final {
  public:
    explicit CfOwner(Type value = nullptr) : value_(value) {}
    ~CfOwner() {
        if (value_)
            CFRelease(value_);
    }
    CfOwner(const CfOwner&) = delete;
    CfOwner& operator=(const CfOwner&) = delete;
    CfOwner(CfOwner&& other) noexcept : value_(std::exchange(other.value_, nullptr)) {}
    [[nodiscard]] Type get() const noexcept {
        return value_;
    }

  private:
    Type value_{};
};

struct Options final {
    std::filesystem::path mesh;
    std::filesystem::path colmapModel;
    std::filesystem::path metricRig;
    std::filesystem::path images;
    std::filesystem::path output;
    TextureBakeConfig bake;
    std::size_t maximumImageDimension{4096};
    bool dryRun{};
    bool json{};
};

struct Calibration final {
    std::size_t width{};
    std::size_t height{};
    float fx{};
    float fy{};
    float cx{};
    float cy{};
    TextureCameraModel model{TextureCameraModel::pinhole};
    float k1{};
    float k2{};
    float k3{};
    float p1{};
    float p2{};
};

struct RigSource final {
    std::filesystem::path rig;
    std::filesystem::path images;
    std::size_t maximumImageDimension{};
};

std::string escapeJson(std::string_view value) {
    std::string result;
    for (const char rawCharacter : value) {
        const auto character = static_cast<unsigned char>(rawCharacter);
        if (character == '"')
            result += "\\\"";
        else if (character == '\\')
            result += "\\\\";
        else if (character == '\n')
            result += "\\n";
        else if (character == '\r')
            result += "\\r";
        else if (character == '\t')
            result += "\\t";
        else if (character < 0x20U)
            result += '?';
        else
            result += static_cast<char>(character);
    }
    return result;
}

aether::Result<std::string> hashFile(const std::filesystem::path& path) {
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    if (error || size == 0)
        return aether::fail(aether::ErrorCode::io, "Unable to hash input file", path);
    std::ifstream stream(path, std::ios::binary);
    aether::package::Sha256 hash;
    std::vector<std::byte> buffer(std::size_t{1024} * 1024);
    std::uintmax_t remaining = size;
    while (remaining > 0) {
        const auto count = static_cast<std::size_t>(
            std::min<std::uintmax_t>(remaining, static_cast<std::uintmax_t>(buffer.size())));
        stream.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(count));
        if (stream.gcount() != static_cast<std::streamsize>(count))
            return aether::fail(aether::ErrorCode::io, "Unable to hash complete input file", path);
        hash.update(std::span<const std::byte>(buffer.data(), count));
        remaining -= count;
    }
    return aether::package::Sha256::hex(hash.finalize());
}

aether::Result<void> writeAtomic(const std::filesystem::path& destination,
                                 std::string_view contents) {
    std::error_code error;
    if (!destination.parent_path().empty())
        std::filesystem::create_directories(destination.parent_path(), error);
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to create provenance directory",
                            destination.parent_path());
    auto temporary = destination;
    temporary += ".tmp";
    std::filesystem::remove(temporary, error);
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(contents.data(), static_cast<std::streamsize>(contents.size()));
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to write texture provenance",
                            destination);
    }
    std::filesystem::rename(temporary, destination, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io,
                            "Unable to publish texture provenance atomically", destination);
    }
    return {};
}

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"texture-bake-error\",\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

int usage() {
    std::cout << "Usage: maveb-texture-bake <metric-mesh.ply> --colmap <text-model> "
                 "--metric-rig <metric-camera-rig.json> --images <root> --output <model.glb> "
                 "[--atlas-size 4096] [--visibility-size 512] [--max-image-dimension 4096] "
                 "[--dry-run] [--json]\n";
    return 0;
}

std::optional<std::size_t> parseSize(std::string_view text) {
    std::size_t value{};
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    return error == std::errc{} && end == text.data() + text.size() && value > 0
               ? std::optional<std::size_t>{value}
               : std::nullopt;
}

std::optional<Options> parseOptions(int argc, char** argv, int& exitCode) {
    Options options;
    for (int index = 1; index < argc; ++index)
        if (std::string_view(argv[index]) == "--json")
            options.json = true;
    auto pathValue = [&](int& index, std::filesystem::path& destination, std::string_view name) {
        if (++index >= argc) {
            exitCode = fail(std::string(name) + " requires a path", options.json);
            return false;
        }
        destination = argv[index];
        return true;
    };
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--help" || argument == "-h") {
            exitCode = usage();
            return std::nullopt;
        }
        if (argument == "--json")
            options.json = true;
        else if (argument == "--dry-run")
            options.dryRun = true;
        else if (argument == "--colmap") {
            if (!pathValue(index, options.colmapModel, argument))
                return std::nullopt;
        } else if (argument == "--metric-rig") {
            if (!pathValue(index, options.metricRig, argument))
                return std::nullopt;
        } else if (argument == "--images") {
            if (!pathValue(index, options.images, argument))
                return std::nullopt;
        } else if (argument == "--output" || argument == "-o") {
            if (!pathValue(index, options.output, argument))
                return std::nullopt;
        } else if (argument == "--atlas-size" || argument == "--visibility-size" ||
                   argument == "--max-image-dimension") {
            ++index;
            if (index >= argc) {
                exitCode =
                    fail(std::string(argument) + " requires a positive integer", options.json);
                return std::nullopt;
            }
            const auto parsed = parseSize(argv[index]);
            if (!parsed) {
                exitCode =
                    fail(std::string(argument) + " requires a positive integer", options.json);
                return std::nullopt;
            }
            const auto value = *parsed;
            if (argument == "--atlas-size")
                options.bake.atlasSize = value;
            else if (argument == "--max-image-dimension")
                options.maximumImageDimension = value;
            else
                options.bake.visibilityWidth = options.bake.visibilityHeight = value;
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.mesh.empty())
            options.mesh = argument;
        else {
            exitCode = fail("Only one mesh input may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.mesh.empty() || options.colmapModel.empty() || options.metricRig.empty() ||
        options.images.empty() || options.output.empty()) {
        exitCode =
            fail("Mesh, --colmap, --metric-rig, --images, and --output are required", options.json);
        return std::nullopt;
    }
    if (options.output.extension() != ".glb") {
        exitCode = fail("Texture bake output must use the .glb extension", options.json);
        return std::nullopt;
    }
    return options;
}

aether::Result<std::unordered_map<std::uint64_t, Calibration>>
loadCalibrations(const std::filesystem::path& path) {
    std::ifstream stream(path);
    if (!stream)
        return aether::fail(aether::ErrorCode::notFound, "Unable to open COLMAP cameras.txt", path);
    std::unordered_map<std::uint64_t, Calibration> result;
    std::string line;
    while (std::getline(stream, line)) {
        if (line.empty() || line.front() == '#')
            continue;
        std::istringstream parser(line);
        std::uint64_t id{};
        std::string model;
        std::size_t width{}, height{};
        if (!(parser >> id >> model >> width >> height) || id == 0 || width < 2 || height < 2)
            return aether::fail(aether::ErrorCode::corruptData, "Malformed COLMAP camera record",
                                path);
        std::vector<double> parameters;
        double value{};
        while (parser >> value)
            parameters.push_back(value);
        Calibration camera{width, height};
        if (model == "SIMPLE_PINHOLE" && parameters.size() == 3) {
            camera.fx = camera.fy = static_cast<float>(parameters[0]);
            camera.cx = static_cast<float>(parameters[1]);
            camera.cy = static_cast<float>(parameters[2]);
        } else if (model == "PINHOLE" && parameters.size() == 4) {
            camera.fx = static_cast<float>(parameters[0]);
            camera.fy = static_cast<float>(parameters[1]);
            camera.cx = static_cast<float>(parameters[2]);
            camera.cy = static_cast<float>(parameters[3]);
        } else if (model == "SIMPLE_RADIAL" && parameters.size() == 4) {
            camera.model = TextureCameraModel::radial;
            camera.fx = camera.fy = static_cast<float>(parameters[0]);
            camera.cx = static_cast<float>(parameters[1]);
            camera.cy = static_cast<float>(parameters[2]);
            camera.k1 = static_cast<float>(parameters[3]);
        } else if (model == "RADIAL" && parameters.size() == 5) {
            camera.model = TextureCameraModel::radial;
            camera.fx = camera.fy = static_cast<float>(parameters[0]);
            camera.cx = static_cast<float>(parameters[1]);
            camera.cy = static_cast<float>(parameters[2]);
            camera.k1 = static_cast<float>(parameters[3]);
            camera.k2 = static_cast<float>(parameters[4]);
        } else if (model == "OPENCV" && parameters.size() == 8) {
            camera.model = TextureCameraModel::opencv;
            camera.fx = static_cast<float>(parameters[0]);
            camera.fy = static_cast<float>(parameters[1]);
            camera.cx = static_cast<float>(parameters[2]);
            camera.cy = static_cast<float>(parameters[3]);
            camera.k1 = static_cast<float>(parameters[4]);
            camera.k2 = static_cast<float>(parameters[5]);
            camera.p1 = static_cast<float>(parameters[6]);
            camera.p2 = static_cast<float>(parameters[7]);
        } else
            return aether::fail(aether::ErrorCode::unsupported, "Unsupported COLMAP camera model",
                                model);
        if (!result.emplace(id, camera).second)
            return aether::fail(aether::ErrorCode::corruptData, "Duplicate COLMAP camera ID", path);
    }
    if (result.empty())
        return aether::fail(aether::ErrorCode::corruptData, "COLMAP cameras.txt is empty", path);
    return result;
}

simd_float4x4 poseMatrix(const std::array<double, 3>& translation,
                         const std::array<double, 4>& quaternion) {
    const double w = quaternion[0], x = quaternion[1], y = quaternion[2], z = quaternion[3];
    simd_float4x4 result = matrix_identity_float4x4;
    result.columns[0] = {static_cast<float>(1 - 2 * (y * y + z * z)),
                         static_cast<float>(2 * (x * y + w * z)),
                         static_cast<float>(2 * (x * z - w * y)), 0};
    result.columns[1] = {static_cast<float>(2 * (x * y - w * z)),
                         static_cast<float>(1 - 2 * (x * x + z * z)),
                         static_cast<float>(2 * (y * z + w * x)), 0};
    result.columns[2] = {static_cast<float>(2 * (x * z + w * y)),
                         static_cast<float>(2 * (y * z - w * x)),
                         static_cast<float>(1 - 2 * (x * x + y * y)), 0};
    result.columns[3] = {static_cast<float>(translation[0]), static_cast<float>(translation[1]),
                         static_cast<float>(translation[2]), 1};
    return result;
}

aether::Result<TextureBakeImage> decodeImage(const std::filesystem::path& path,
                                             std::size_t maximumDimension) {
    std::error_code fileError;
    const auto fileBytes = std::filesystem::file_size(path, fileError);
    if (fileError || fileBytes == 0 || fileBytes > 1ULL * 1024ULL * 1024ULL * 1024ULL)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Texture source is missing, empty, or exceeds 1 GiB", path);
    const auto pathString = path.string();
    CfOwner<CFURLRef> url(CFURLCreateFromFileSystemRepresentation(
        nullptr, reinterpret_cast<const UInt8*>(pathString.data()),
        static_cast<CFIndex>(pathString.size()), false));
    CfOwner<CGImageSourceRef> source(url.get() ? CGImageSourceCreateWithURL(url.get(), nullptr)
                                               : nullptr);
    if (!source.get())
        return aether::fail(aether::ErrorCode::corruptData, "ImageIO cannot open texture source",
                            path);
    const void* keys[]{kCGImageSourceCreateThumbnailFromImageAlways,
                       kCGImageSourceCreateThumbnailWithTransform,
                       kCGImageSourceThumbnailMaxPixelSize};
    if (maximumDimension < 2 || maximumDimension > 16384)
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Maximum decoded image dimension must be between 2 and 16384");
    const auto maximum = static_cast<int>(maximumDimension);
    CfOwner<CFNumberRef> maximumNumber(CFNumberCreate(nullptr, kCFNumberIntType, &maximum));
    const void* values[]{kCFBooleanTrue, kCFBooleanTrue, maximumNumber.get()};
    CfOwner<CFDictionaryRef> options(CFDictionaryCreate(nullptr, keys, values, 3,
                                                        &kCFTypeDictionaryKeyCallBacks,
                                                        &kCFTypeDictionaryValueCallBacks));
    CfOwner<CGImageRef> image(CGImageSourceCreateThumbnailAtIndex(source.get(), 0, options.get()));
    if (!image.get())
        return aether::fail(aether::ErrorCode::corruptData, "ImageIO cannot decode texture source",
                            path);
    const std::size_t width = CGImageGetWidth(image.get()), height = CGImageGetHeight(image.get());
    if (width < 2 || height < 2 || width > 16384 || height > 16384 || width > 268435456ULL / height)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Texture image dimensions are unsafe", path);
    std::vector<std::uint8_t> rgba(width * height * 4);
    CfOwner<CGColorSpaceRef> space(CGColorSpaceCreateWithName(kCGColorSpaceSRGB));
    const auto bitmapInfo =
        static_cast<CGBitmapInfo>(static_cast<std::uint32_t>(kCGImageAlphaPremultipliedLast) |
                                  static_cast<std::uint32_t>(kCGBitmapByteOrder32Big));
    CfOwner<CGContextRef> context(
        CGBitmapContextCreate(rgba.data(), width, height, 8, width * 4, space.get(), bitmapInfo));
    if (!context.get())
        return aether::fail(aether::ErrorCode::internal, "Unable to allocate image decode context");
    CGContextTranslateCTM(context.get(), 0.0, static_cast<double>(height));
    CGContextScaleCTM(context.get(), 1.0, -1.0);
    CGContextDrawImage(context.get(),
                       CGRectMake(0, 0, static_cast<double>(width), static_cast<double>(height)),
                       image.get());
    TextureBakeImage result{width, height, {}};
    result.pixels.resize(width * height);
    auto linear = [](float value) {
        return value <= 0.04045F ? value / 12.92F : std::pow((value + 0.055F) / 1.055F, 2.4F);
    };
    for (std::size_t index = 0; index < result.pixels.size(); ++index)
        result.pixels[index] = {linear(static_cast<float>(rgba[index * 4]) / 255.0F),
                                linear(static_cast<float>(rgba[index * 4 + 1]) / 255.0F),
                                linear(static_cast<float>(rgba[index * 4 + 2]) / 255.0F)};
    return result;
}

aether::Result<std::vector<std::byte>> encodePng(std::span<const simd_float3> pixels,
                                                 std::size_t width, std::size_t height) {
    std::vector<std::uint8_t> rgba(width * height * 4);
    auto srgb = [](float value) {
        value = std::clamp(value, 0.0F, 1.0F);
        return value <= 0.0031308F ? 12.92F * value
                                   : 1.055F * std::pow(value, 1.0F / 2.4F) - 0.055F;
    };
    for (std::size_t index = 0; index < pixels.size(); ++index) {
        rgba[index * 4] = static_cast<std::uint8_t>(std::lround(srgb(pixels[index].x) * 255.0F));
        rgba[index * 4 + 1] =
            static_cast<std::uint8_t>(std::lround(srgb(pixels[index].y) * 255.0F));
        rgba[index * 4 + 2] =
            static_cast<std::uint8_t>(std::lround(srgb(pixels[index].z) * 255.0F));
        rgba[index * 4 + 3] = 255;
    }
    CfOwner<CGColorSpaceRef> space(CGColorSpaceCreateWithName(kCGColorSpaceSRGB));
    const auto bitmapInfo =
        static_cast<CGBitmapInfo>(static_cast<std::uint32_t>(kCGImageAlphaPremultipliedLast) |
                                  static_cast<std::uint32_t>(kCGBitmapByteOrder32Big));
    CfOwner<CGContextRef> context(
        CGBitmapContextCreate(rgba.data(), width, height, 8, width * 4, space.get(), bitmapInfo));
    CfOwner<CGImageRef> image(context.get() ? CGBitmapContextCreateImage(context.get()) : nullptr);
    CfOwner<CFMutableDataRef> data(CFDataCreateMutable(nullptr, 0));
    CfOwner<CGImageDestinationRef> destination(
        data.get() ? CGImageDestinationCreateWithData(data.get(), CFSTR("public.png"), 1, nullptr)
                   : nullptr);
    if (!image.get() || !destination.get())
        return aether::fail(aether::ErrorCode::internal, "Unable to create PNG encoder");
    CGImageDestinationAddImage(destination.get(), image.get(), nullptr);
    if (!CGImageDestinationFinalize(destination.get()))
        return aether::fail(aether::ErrorCode::io, "Unable to encode texture PNG");
    const auto size = static_cast<std::size_t>(CFDataGetLength(data.get()));
    std::vector<std::byte> result(size);
    std::memcpy(result.data(), CFDataGetBytePtr(data.get()), size);
    return result;
}

aether::Result<std::vector<TextureBakeCamera>>
loadRig(const RigSource& source,
        const std::unordered_map<std::uint64_t, Calibration>& calibrations) {
    const auto& path = source.rig;
    std::error_code fileError;
    const auto fileBytes = std::filesystem::file_size(path, fileError);
    if (fileError || fileBytes == 0 || fileBytes > 64ULL * 1024ULL * 1024ULL)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Metric camera rig is missing, empty, or exceeds 64 MiB", path);
    constexpr std::size_t maximumRigBytes = 64ULL * 1024ULL * 1024ULL;
    std::vector<char> json(maximumRigBytes + simdjson::SIMDJSON_PADDING);
    std::ifstream stream(path, std::ios::binary);
    stream.read(json.data(), static_cast<std::streamsize>(fileBytes));
    if (stream.gcount() != static_cast<std::streamsize>(fileBytes))
        return aether::fail(aether::ErrorCode::io, "Unable to read complete metric camera rig",
                            path);
    simdjson::dom::parser parser(maximumRigBytes);
    if (parser.allocate(maximumRigBytes))
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Unable to allocate bounded metric-rig parser");
    simdjson::dom::element root;
    if (parser.parse(json.data(), static_cast<std::size_t>(fileBytes), false).get(root))
        return aether::fail(aether::ErrorCode::corruptData, "Unable to parse metric camera rig",
                            path);
    bool accepted{};
    std::uint64_t schema{};
    if (root["schemaVersion"].get(schema) || schema != 1 || root["accepted"].get(accepted) ||
        !accepted)
        return aether::fail(aether::ErrorCode::corruptData,
                            "Metric camera rig is not accepted schema v1", path);
    simdjson::dom::array entries;
    if (root["metricCameras"].get(entries))
        return aether::fail(aether::ErrorCode::corruptData, "Metric camera rig has no cameras",
                            path);
    std::vector<TextureBakeCamera> result;
    std::unordered_set<std::string> imageNames;
    for (auto entry : entries) {
        std::uint64_t cameraId{};
        std::string_view name;
        simdjson::dom::array translationValues, orientationValues;
        if (entry["cameraId"].get(cameraId) || entry["imageName"].get(name) ||
            entry["cameraToMetricWorld"]["translation"].get(translationValues) ||
            entry["cameraToMetricWorld"]["orientationWxyz"].get(orientationValues) ||
            translationValues.size() != 3 || orientationValues.size() != 4)
            return aether::fail(aether::ErrorCode::corruptData, "Malformed metric camera record",
                                path);
        const std::filesystem::path relative(name);
        if (relative.empty() || relative.is_absolute() ||
            std::ranges::any_of(relative, [](const auto& part) { return part == ".."; }))
            return aether::fail(aether::ErrorCode::corruptData,
                                "Metric camera image path is unsafe", relative);
        if (!imageNames.insert(std::string(name)).second)
            return aether::fail(aether::ErrorCode::corruptData,
                                "Metric camera rig repeats an image name", relative);
        const auto calibration = calibrations.find(cameraId);
        if (calibration == calibrations.end())
            return aether::fail(aether::ErrorCode::corruptData,
                                "Metric camera calibration is missing", relative);
        std::array<double, 3> translation{};
        std::array<double, 4> orientation{};
        std::size_t index{};
        for (auto value : translationValues) {
            if (value.get(translation[index++]))
                return aether::fail(aether::ErrorCode::corruptData, "Invalid camera translation",
                                    relative);
        }
        index = 0;
        for (auto value : orientationValues) {
            if (value.get(orientation[index++]))
                return aether::fail(aether::ErrorCode::corruptData, "Invalid camera orientation",
                                    relative);
        }
        const double length = std::sqrt(
            std::inner_product(orientation.begin(), orientation.end(), orientation.begin(), 0.0));
        if (!std::isfinite(length) || std::abs(length - 1.0) > 1.0e-4)
            return aether::fail(aether::ErrorCode::corruptData,
                                "Camera quaternion is not normalized", relative);
        auto decoded = decodeImage(source.images / relative, source.maximumImageDimension);
        if (!decoded)
            return std::unexpected(decoded.error());
        const auto& cameraCalibration = calibration->second;
        const float scaleX =
            static_cast<float>(decoded->width) / static_cast<float>(cameraCalibration.width);
        const float scaleY =
            static_cast<float>(decoded->height) / static_cast<float>(cameraCalibration.height);
        if (std::abs(scaleX - scaleY) > 1.0e-4F)
            return aether::fail(aether::ErrorCode::corruptData,
                                "Decoded image aspect ratio does not match COLMAP calibration",
                                relative);
        TextureBakeCamera camera;
        camera.imageName = std::string(name);
        camera.focalX = cameraCalibration.fx * scaleX;
        camera.focalY = cameraCalibration.fy * scaleY;
        camera.principalX = cameraCalibration.cx * scaleX;
        camera.principalY = cameraCalibration.cy * scaleY;
        camera.model = cameraCalibration.model;
        camera.k1 = cameraCalibration.k1;
        camera.k2 = cameraCalibration.k2;
        camera.k3 = cameraCalibration.k3;
        camera.p1 = cameraCalibration.p1;
        camera.p2 = cameraCalibration.p2;
        camera.cameraToWorld = poseMatrix(translation, orientation);
        camera.image = std::move(*decoded);
        result.push_back(std::move(camera));
    }
    if (result.empty())
        return aether::fail(aether::ErrorCode::corruptData, "Metric camera rig is empty", path);
    return result;
}

int run(int argc, char** argv) {
    int parseExitCode{};
    auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;
    auto proxy = aether::hybrid::ProxyPlyLoader::load(options->mesh);
    if (!proxy)
        return fail(proxy.error().describe(), options->json, 3);
    auto calibrations = loadCalibrations(options->colmapModel / "cameras.txt");
    if (!calibrations)
        return fail(calibrations.error().describe(), options->json, 3);
    auto cameras =
        loadRig(RigSource{options->metricRig, options->images, options->maximumImageDimension},
                *calibrations);
    if (!cameras)
        return fail(cameras.error().describe(), options->json, 3);
    aether::mesh::MeshPrimitive primitive;
    primitive.name = "Maveb metric canonical mesh";
    primitive.vertices.reserve(proxy->vertices.size());
    primitive.indices = proxy->indices;
    for (const auto& source : proxy->vertices) {
        aether::mesh::MeshVertex vertex{};
        vertex.position = {source.position[0], source.position[1], source.position[2]};
        vertex.normal = {source.normal[0], source.normal[1], source.normal[2]};
        vertex.tangent = {1, 0, 0, 1};
        primitive.vertices.push_back(vertex);
    }
    auto baked = aether::reconstruction::TextureBaker::bake(primitive, *cameras, options->bake);
    if (!baked)
        return fail(baked.error().describe(), options->json, 4);
    auto png = encodePng(baked->atlasPixels, baked->atlasWidth, baked->atlasHeight);
    if (!png)
        return fail(png.error().describe(), options->json, 4);
    aether::mesh::MeshAsset asset;
    asset.name = "Maveb textured metric reconstruction";
    baked->primitive.materialIndex = 1;
    asset.primitives.push_back(std::move(baked->primitive));
    asset.materials.emplace_back(); // Slot 0 is the implicit default material.
    aether::mesh::PbrMaterial material;
    material.name = "Baked appearance";
    material.metallic = 0;
    material.roughness = 1;
    material.baseColorTexture = 0;
    asset.materials.push_back(material);
    asset.images.push_back({"maveb-baked-base-color.png", std::move(*png)});
    aether::mesh::TextureAsset texture;
    texture.imageIndex = 0;
    texture.addressU = texture.addressV = aether::mesh::SamplerAddressMode::clampToEdge;
    asset.textures.push_back(texture);
    auto destination = options->output;
    if (options->dryRun)
        destination += ".dry-run.tmp.glb";
    std::error_code error;
    std::filesystem::remove(destination, error);
    auto exported = aether::mesh::GltfExporter::writeStatic(asset, destination);
    if (!exported)
        return fail(exported.error().describe(), options->json, 5);
    auto roundTrip = aether::mesh::GltfLoader::load(destination);
    if (!roundTrip) {
        std::filesystem::remove(destination, error);
        return fail("Generated GLB failed strict round-trip: " + roundTrip.error().describe(),
                    options->json, 5);
    }
    std::ifstream stream(destination, std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(stream)), {});
    const auto hash = aether::package::Sha256::hex(
        aether::package::Sha256::hash(std::as_bytes(std::span(bytes))));
    auto provenancePath = options->output;
    provenancePath += ".provenance.json";
    if (options->dryRun) {
        std::filesystem::remove(destination, error);
    } else {
        auto meshHash = hashFile(options->mesh);
        auto calibrationHash = hashFile(options->colmapModel / "cameras.txt");
        auto rigHash = hashFile(options->metricRig);
        if (!meshHash || !calibrationHash || !rigHash) {
            std::filesystem::remove(destination, error);
            return fail("Unable to hash texture bake provenance", options->json, 5);
        }
        std::vector<std::pair<std::string, std::string>> imageHashes;
        for (const auto& camera : *cameras) {
            auto imageHash = hashFile(options->images / camera.imageName);
            if (!imageHash) {
                std::filesystem::remove(destination, error);
                return fail(imageHash.error().describe(), options->json, 5);
            }
            imageHashes.emplace_back(camera.imageName, std::move(*imageHash));
        }
        std::ostringstream provenance;
        provenance.imbue(std::locale::classic());
        provenance << std::setprecision(std::numeric_limits<double>::max_digits10)
                   << "{\"schemaVersion\":1,\"inputs\":{\"meshSha256\":\"" << *meshHash
                   << "\",\"colmapCamerasSha256\":\"" << *calibrationHash
                   << "\",\"metricRigSha256\":\"" << *rigHash << "\",\"images\":[";
        for (std::size_t index = 0; index < imageHashes.size(); ++index) {
            if (index > 0)
                provenance << ',';
            provenance << "{\"name\":\"" << escapeJson(imageHashes[index].first)
                       << "\",\"sha256\":\"" << imageHashes[index].second << "\"}";
        }
        provenance << "]},\"configuration\":{\"atlasSize\":" << options->bake.atlasSize
                   << ",\"visibilityWidth\":" << options->bake.visibilityWidth
                   << ",\"visibilityHeight\":" << options->bake.visibilityHeight
                   << ",\"gutterPixels\":" << options->bake.gutterPixels
                   << ",\"maximumCamerasPerTriangle\":" << options->bake.maximumCamerasPerTriangle
                   << "},\"result\":{\"glbSha256\":\"" << hash
                   << "\",\"glbBytes\":" << bytes.size()
                   << ",\"triangles\":" << baked->report.triangles
                   << ",\"cameras\":" << baked->report.cameras
                   << ",\"coverage\":" << baked->report.coverage
                   << ",\"texturedTexels\":" << baked->report.texturedTexels
                   << ",\"unobservedTexels\":" << baked->report.unobservedTexels
                   << ",\"exposureGains\":[";
        for (std::size_t index = 0; index < baked->report.exposureGains.size(); ++index) {
            if (index > 0)
                provenance << ',';
            provenance << baked->report.exposureGains[index];
        }
        provenance << "]}}\n";
        auto written = writeAtomic(provenancePath, provenance.str());
        if (!written) {
            std::filesystem::remove(destination, error);
            return fail(written.error().describe(), options->json, 5);
        }
    }
    if (options->json)
        std::cout << "{\"ok\":true,\"dryRun\":" << (options->dryRun ? "true" : "false")
                  << ",\"output\":\"" << escapeJson(options->output.string()) << "\",\"sha256\":\""
                  << hash << "\",\"provenance\":\"" << escapeJson(provenancePath.string())
                  << "\",\"triangles\":" << baked->report.triangles
                  << ",\"cameras\":" << baked->report.cameras
                  << ",\"coverage\":" << baked->report.coverage
                  << ",\"textureBytes\":" << asset.images[0].bytes.size()
                  << ",\"glbBytes\":" << bytes.size() << "}\n";
    else
        std::cout << "Baked metric textured GLB from " << baked->report.cameras << " cameras with "
                  << baked->report.coverage * 100.0F << "% observed texel coverage\n";
    return 0;
}

bool requestsJson(int argc, char** argv) noexcept {
    for (int i = 1; i < argc; ++i)
        if (std::strcmp(argv[i], "--json") == 0)
            return true;
    return false;
}
} // namespace

int main(int argc, char** argv) noexcept {
    const bool json = requestsJson(argc, argv);
    try {
        return run(argc, argv);
    } catch (const std::exception& error) {
        if (!json)
            std::fprintf(stderr, "Unhandled texture bake failure: %s\n", error.what());
        else
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                       "texture bake failure\"}}\n",
                       stderr);
    } catch (...) {
        std::fputs(json ? "{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                          "texture bake failure\"}}\n"
                        : "Unhandled texture bake failure\n",
                   stderr);
    }
    return 6;
}
