#include <aether/mesh/GltfExporter.hpp>
#include <aether/mesh/GltfLoader.hpp>
#include <aether/package/Sha256.hpp>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace {
struct Options final {
    std::filesystem::path input;
    std::filesystem::path output;
    bool dryRun{};
    bool json{};
};

std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size());
    for (const char character : value) {
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
        }
    }
    return result;
}

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"glb-export-error\",\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

int usage() {
    std::cout << "Usage: aether-export-glb <input.gltf|input.glb> --output <output.glb> "
                 "[--dry-run] [--json]\n\n"
                 "Writes a deterministic, self-contained static glTF 2 GLB. Animation, skins, "
                 "morph targets, external output resources, and unsupported image encodings are "
                 "rejected rather than discarded.\n";
    return 0;
}

std::optional<Options> parseOptions(int argc, char** argv, int& exitCode) {
    Options options;
    for (int index = 1; index < argc; ++index)
        if (std::string_view(argv[index]) == "--json")
            options.json = true;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--help" || argument == "-h") {
            exitCode = usage();
            return std::nullopt;
        }
        if (argument == "--json") {
            options.json = true;
        } else if (argument == "--dry-run") {
            options.dryRun = true;
        } else if (argument == "--output" || argument == "-o") {
            if (++index >= argc) {
                exitCode = fail("--output requires a path", options.json);
                return std::nullopt;
            }
            options.output = argv[index];
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.input.empty()) {
            options.input = argument;
        } else {
            exitCode = fail("Only one input asset may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.input.empty() || options.output.empty()) {
        exitCode = fail("Input asset and --output are required", options.json);
        return std::nullopt;
    }
    if (options.output.extension() != ".glb") {
        exitCode = fail("Native export destination must use the .glb extension", options.json);
        return std::nullopt;
    }
    return options;
}

aether::Result<aether::package::Sha256Digest> hashFile(const std::filesystem::path& path) {
    std::error_code error;
    const auto bytes = std::filesystem::file_size(path, error);
    if (error || bytes == 0)
        return aether::fail(aether::ErrorCode::io, "Unable to size exported GLB", path);
    std::ifstream stream(path, std::ios::binary);
    aether::package::Sha256 hash;
    std::vector<std::byte> buffer(std::size_t{1024} * 1024);
    std::uintmax_t remaining = bytes;
    while (remaining > 0) {
        const auto amount = static_cast<std::size_t>(
            std::min<std::uintmax_t>(remaining, static_cast<std::uintmax_t>(buffer.size())));
        stream.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(amount));
        if (stream.gcount() != static_cast<std::streamsize>(amount))
            return aether::fail(aether::ErrorCode::io, "Unable to hash complete exported GLB",
                                path);
        hash.update(std::span<const std::byte>(buffer.data(), amount));
        remaining -= amount;
    }
    return hash.finalize();
}

int run(int argc, char** argv) {
    int parseExitCode{};
    auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;
    auto asset = aether::mesh::GltfLoader::load(options->input);
    if (!asset)
        return fail(asset.error().describe(), options->json, 3);

    auto validationPath = options->output;
    if (options->dryRun)
        validationPath += ".dry-run.tmp.glb";
    std::error_code filesystemError;
    std::filesystem::remove(validationPath, filesystemError);
    auto encoded = aether::mesh::GltfExporter::encodeStatic(*asset);
    if (!encoded)
        return fail(encoded.error().describe(), options->json, 4);

    auto written = aether::mesh::GltfExporter::writeStatic(*asset, validationPath);
    if (!written)
        return fail(written.error().describe(), options->json, 4);

    const auto outputBytes = encoded->size();
    std::size_t vertices = 0;
    std::size_t triangles = 0;
    for (const auto& primitive : asset->primitives) {
        vertices += primitive.vertices.size();
        triangles += primitive.indices.size() / 3;
    }
    const auto primitives = asset->primitives.size();
    const auto instances = asset->instances.size();
    const auto materials = asset->materials.size();
    const auto textures = asset->textures.size();
    const auto images = asset->images.size();
    auto roundTrip = aether::mesh::GltfLoader::load(validationPath);
    if (!roundTrip) {
        std::filesystem::remove(validationPath, filesystemError);
        return fail("Exported GLB failed strict round-trip validation: " +
                        roundTrip.error().describe(),
                    options->json, 4);
    }
    auto hash = hashFile(validationPath);
    if (!hash) {
        std::filesystem::remove(validationPath, filesystemError);
        return fail(hash.error().describe(), options->json, 4);
    }
    if (options->dryRun)
        std::filesystem::remove(validationPath, filesystemError);
    if (options->dryRun && filesystemError)
        return fail("Unable to remove dry-run GLB artifact", options->json, 4);

    if (options->json) {
        std::cout << "{\"ok\":true,\"dryRun\":" << (options->dryRun ? "true" : "false")
                  << ",\"input\":\"" << escapeJson(options->input.string()) << "\",\"output\":\""
                  << escapeJson(options->output.string()) << "\",\"sha256\":\""
                  << aether::package::Sha256::hex(*hash) << "\",\"bytes\":" << outputBytes
                  << ",\"primitives\":" << primitives
                  << ",\"instances\":" << instances << ",\"vertices\":" << vertices
                  << ",\"triangles\":" << triangles
                  << ",\"materials\":" << materials << ",\"textures\":" << textures
                  << ",\"images\":" << images << "}\n";
    } else {
        std::cout << (options->dryRun ? "Validated" : "Exported") << " native GLB with "
                  << vertices << " vertices and " << triangles << " triangles\n";
    }
    return 0;
}

bool requestsJson(int argc, char** argv) noexcept {
    for (int index = 1; index < argc; ++index)
        if (std::strcmp(argv[index], "--json") == 0)
            return true;
    return false;
}
} // namespace

int main(int argc, char** argv) noexcept {
    const bool json = requestsJson(argc, argv);
    try {
        return run(argc, argv);
    } catch (const std::exception& error) {
        if (json)
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                       "GLB export failure\"}}\n",
                       stderr);
        else
            std::fprintf(stderr, "Unhandled GLB export failure: %s\n", error.what());
    } catch (...) {
        if (json)
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                       "GLB export failure\"}}\n",
                       stderr);
        else
            std::fputs("Unhandled GLB export failure\n", stderr);
    }
    return 5;
}
