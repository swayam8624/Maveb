#include <aether/gaussian/PlyLoader.hpp>
#include <aether/gaussian/ReferenceRasterizer.hpp>

#include <simdjson.h>

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

struct Options final {
    std::filesystem::path gaussianPath;
    std::filesystem::path targetsPath;
    std::filesystem::path outputPath;
    std::size_t targetIndex{};
    bool json{};
};

std::string jsonEscape(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (const char character : text) {
        switch (character) {
        case '\\':
            result += "\\\\";
            break;
        case '"':
            result += "\\\"";
            break;
        case '\n':
            result += "\\n";
            break;
        case '\r':
            result += "\\r";
            break;
        case '\t':
            result += "\\t";
            break;
        default:
            result += character;
            break;
        }
    }
    return result;
}

std::optional<Options> parseOptions(int argc, char** argv) {
    if (argc < 3)
        return std::nullopt;
    Options options;
    options.gaussianPath = argv[1];
    options.targetsPath = argv[2];
    bool haveTarget = false;
    for (int index = 3; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--target-index" && index + 1 < argc) {
            try {
                const auto parsed = std::stoull(argv[++index]);
                options.targetIndex = static_cast<std::size_t>(parsed);
                haveTarget = true;
            } catch (...) {
                return std::nullopt;
            }
        } else if (argument == "--output" && index + 1 < argc) {
            options.outputPath = argv[++index];
        } else if (argument == "--json") {
            options.json = true;
        } else {
            return std::nullopt;
        }
    }
    if (!haveTarget || options.outputPath.empty())
        return std::nullopt;
    return options;
}

void printHelp() {
    std::cerr << "Usage: maveb-gaussian-depth <gaussians.ply> <targets.json> "
                 "--target-index <n> --output <depth.f32> [--json]\n";
}

std::uint64_t uintField(simdjson::dom::element object, const char* field) {
    std::uint64_t value{};
    if (object[field].get(value))
        throw std::runtime_error(std::string("invalid integer field: ") + field);
    return value;
}

template <std::size_t Size>
std::array<float, Size> floatArray(simdjson::dom::element object, const char* field) {
    simdjson::dom::array values;
    if (object[field].get_array().get(values) || values.size() != Size)
        throw std::runtime_error(std::string("invalid numeric array: ") + field);
    std::array<float, Size> result{};
    std::size_t index = 0;
    for (auto value : values) {
        double parsed{};
        if (value.get(parsed) || !std::isfinite(parsed))
            throw std::runtime_error(std::string("non-finite numeric array: ") + field);
        result[index++] = static_cast<float>(parsed);
    }
    return result;
}

simdjson::dom::element targetForIndex(simdjson::dom::element document, std::size_t targetIndex) {
    simdjson::dom::array targets;
    if (document["targets"].get_array().get(targets) || targets.size() == 0)
        throw std::runtime_error("U5a targets.json has no targets");
    for (auto target : targets) {
        if (uintField(target, "targetIndex") == targetIndex)
            return target;
    }
    throw std::runtime_error("requested U5a target index is absent");
}

} // namespace

int main(int argc, char** argv) { // NOLINT(bugprone-exception-escape)
    const auto options = parseOptions(argc, argv);
    if (!options) {
        printHelp();
        return 2;
    }

    try {
        auto asset = aether::gaussian::PlyLoader::load(options->gaussianPath);
        if (!asset)
            throw std::runtime_error(asset.error().describe());

        simdjson::dom::parser parser;
        auto loaded = parser.load(options->targetsPath.string());
        if (loaded.error())
            throw std::runtime_error("unable to parse U5a target manifest");
        simdjson::dom::element document = loaded.value();
        const auto target = targetForIndex(document, options->targetIndex);

        const auto width = uintField(target, "width");
        const auto height = uintField(target, "height");
        if (width == 0 || height == 0)
            throw std::runtime_error("U5a target dimensions are invalid");
        const auto intrinsics = floatArray<4>(target, "intrinsics");
        const auto cameraPosition = floatArray<3>(target, "cameraWorldPosition");
        const auto worldToCamera = floatArray<16>(target, "worldToCameraRowMajor");

        aether::gaussian::ReferenceCamera camera;
        camera.width = static_cast<std::size_t>(width);
        camera.height = static_cast<std::size_t>(height);
        camera.focalX = intrinsics[0];
        camera.focalY = intrinsics[1];
        camera.centerX = intrinsics[2];
        camera.centerY = intrinsics[3];
        camera.nearPlane = 0.05F;
        camera.farPlane = 20.0F;
        camera.cameraWorldPosition = cameraPosition;
        camera.worldToCamera = worldToCamera;

        auto rendered = aether::gaussian::ReferenceRasterizer::render(*asset, camera);
        if (!rendered)
            throw std::runtime_error(rendered.error().describe());
        if (rendered->depth.size() != camera.width * camera.height)
            throw std::runtime_error("reference Gaussian depth size mismatch");

        std::error_code directoryError;
        std::filesystem::create_directories(options->outputPath.parent_path(), directoryError);
        if (directoryError)
            throw std::runtime_error("unable to create Gaussian depth output directory");
        std::ofstream stream(options->outputPath, std::ios::binary);
        if (!stream)
            throw std::runtime_error("unable to open Gaussian depth output");
        stream.write(reinterpret_cast<const char*>(rendered->depth.data()),
                     static_cast<std::streamsize>(rendered->depth.size() * sizeof(float)));
        if (!stream)
            throw std::runtime_error("unable to write Gaussian depth output");

        std::size_t finiteDepth = 0;
        for (const float value : rendered->depth)
            if (std::isfinite(value))
                ++finiteDepth;

        if (options->json) {
            std::cout << "{\"ok\":true,\"gaussians\":" << asset->gaussians.size()
                      << ",\"targetIndex\":" << options->targetIndex << ",\"width\":"
                      << camera.width << ",\"height\":" << camera.height
                      << ",\"finiteDepthPixels\":" << finiteDepth << ",\"output\":\""
                      << jsonEscape(std::filesystem::absolute(options->outputPath).string())
                      << "\"}\n";
        }
        return 0;
    } catch (const std::exception& exception) {
        std::cerr << "{\"ok\":false,\"error\":\"" << jsonEscape(exception.what()) << "\"}\n";
        return 2;
    }
}
