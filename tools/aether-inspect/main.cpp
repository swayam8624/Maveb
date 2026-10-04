#include <aether/canonical/CanonicalAsset.hpp>
#include <aether/package/Package.hpp>
#include <aether/package/Sha256.hpp>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <iostream>
#include <string>
#include <string_view>

namespace {
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

int usage() {
    std::cout << "Usage: aether-inspect [--json] <scene.aether>\n";
    return 0;
}

bool requestsJson(int argc, char** argv) noexcept {
    for (int index = 1; index < argc; ++index)
        if (std::strcmp(argv[index], "--json") == 0)
            return true;
    return false;
}
} // namespace

int run(int argc, char** argv) {
    bool json = false;
    std::filesystem::path path;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--help" || argument == "-h")
            return usage();
        if (argument == "--json")
            json = true;
        else if (path.empty())
            path = argument;
        else {
            std::cerr << "Unexpected argument: " << argument << '\n';
            return 2;
        }
    }
    if (path.empty()) {
        std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"invalid-input\","
                             "\"message\":\"Missing scene path\"}}\n"
                           : "Missing scene path\n");
        return 2;
    }

    auto package = aether::package::PackageReader::open(path);
    if (!package) {
        if (json) {
            std::cerr << "{\"ok\":false,\"error\":{\"code\":\"package-error\",\"message\":\""
                      << escapeJson(package.error().describe()) << "\"}}\n";
        } else {
            std::cerr << package.error().describe() << '\n';
        }
        return 3;
    }
    const auto& info = package->info();
    const auto hasChunk = [&](aether::package::ChunkType type) {
        return std::ranges::any_of(info.chunks,
                                   [&](const auto& chunk) { return chunk.type == type; });
    };
    const bool hasAnyCanonicalChunk = hasChunk(aether::package::ChunkType::canonicalAsset) ||
                                      hasChunk(aether::package::ChunkType::canonicalMesh) ||
                                      hasChunk(aether::package::ChunkType::canonicalConfidence);
    std::optional<aether::canonical::CanonicalManifest> canonicalManifest;
    std::size_t canonicalCameras = 0;
    std::size_t canonicalConfidenceValues = 0;
    if (hasAnyCanonicalChunk) {
        if (info.majorVersion == 1 && info.minorVersion < 1) {
            std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"canonical-asset-error\","
                                 "\"message\":\"Canonical asset chunks require package version "
                                 "1.1 or newer\"}}\n"
                               : "Canonical asset chunks require package version 1.1 or newer\n");
            return 4;
        }
        if (!hasChunk(aether::package::ChunkType::canonicalAsset) ||
            !hasChunk(aether::package::ChunkType::canonicalMesh) ||
            !hasChunk(aether::package::ChunkType::canonicalConfidence) ||
            !hasChunk(aether::package::ChunkType::cameras)) {
            std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"canonical-asset-error\","
                                 "\"message\":\"Canonical asset chunks are incomplete\"}}\n"
                               : "Canonical asset chunks are incomplete\n");
            return 4;
        }
        auto manifestBytes = package->readChunk(aether::package::ChunkType::canonicalAsset);
        auto meshBytes = package->readChunk(aether::package::ChunkType::canonicalMesh);
        auto cameraBytes = package->readChunk(aether::package::ChunkType::cameras);
        auto confidenceBytes = package->readChunk(aether::package::ChunkType::canonicalConfidence);
        if (!manifestBytes || !meshBytes || !cameraBytes || !confidenceBytes) {
            std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"canonical-asset-error\","
                                 "\"message\":\"Unable to read canonical asset chunks\"}}\n"
                               : "Unable to read canonical asset chunks\n");
            return 4;
        }
        auto manifest = aether::canonical::CanonicalAssetLoader::parseManifest(*manifestBytes);
        auto mesh = aether::canonical::CanonicalAssetLoader::validateMeshPayload(*meshBytes);
        auto cameras = aether::canonical::CameraRigCodec::decode(*cameraBytes);
        auto confidence = aether::canonical::ConfidenceCodec::decode(*confidenceBytes);
        if (!manifest || !mesh || !cameras || !confidence) {
            const auto message = !manifest  ? manifest.error().describe()
                                 : !mesh    ? mesh.error().describe()
                                 : !cameras ? cameras.error().describe()
                                            : confidence.error().describe();
            std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"canonical-asset-error\","
                                 "\"message\":\"" +
                                     escapeJson(message) + "\"}}\n"
                               : message + "\n");
            return 4;
        }
        if (confidence->size() != mesh->vertexCount) {
            const std::string message =
                "Canonical confidence count does not match canonical mesh vertices";
            std::cerr << (json ? "{\"ok\":false,\"error\":{\"code\":\"canonical-asset-error\","
                                 "\"message\":\"" +
                                     escapeJson(message) + "\"}}\n"
                               : message + "\n");
            return 4;
        }
        canonicalCameras = cameras->cameras.size();
        canonicalConfidenceValues = confidence->size();
        canonicalManifest = std::move(*manifest);
    }
    if (json) {
        std::cout << "{\"schemaVersion\":1,\"path\":\"" << escapeJson(path.string())
                  << "\",\"packageVersion\":\"" << info.majorVersion << '.' << info.minorVersion
                  << "\",\"bytes\":" << info.fileBytes << ",\"contentHash\":\""
                  << aether::package::Sha256::hex(info.contentHash) << "\",\"chunks\":[";
        for (std::size_t index = 0; index < info.chunks.size(); ++index) {
            const auto& chunk = info.chunks[index];
            if (index > 0)
                std::cout << ',';
            std::cout << "{\"type\":\"" << aether::package::chunkTypeName(chunk.type)
                      << "\",\"required\":" << (chunk.required ? "true" : "false")
                      << ",\"compression\":\""
                      << (chunk.compression == aether::package::Compression::zstd ? "zstd" : "none")
                      << "\",\"storedBytes\":" << chunk.storedBytes
                      << ",\"uncompressedBytes\":" << chunk.uncompressedBytes << '}';
        }
        std::cout << "],\"canonical\":" << (canonicalManifest ? "true" : "false");
        if (canonicalManifest) {
            std::cout << ",\"canonicalAsset\":{\"name\":\"" << escapeJson(canonicalManifest->name)
                      << "\",\"coordinateSystem\":\""
                      << escapeJson(canonicalManifest->coordinateSystem)
                      << "\",\"metersPerUnit\":" << canonicalManifest->metersPerUnit
                      << ",\"cameras\":" << canonicalCameras
                      << ",\"confidenceValues\":" << canonicalConfidenceValues << '}';
        }
        std::cout << "}\n";
    } else {
        std::cout << "Scene: " << path << "\nVersion: " << info.majorVersion << '.'
                  << info.minorVersion << "\nBytes: " << info.fileBytes
                  << "\nContent SHA-256: " << aether::package::Sha256::hex(info.contentHash)
                  << "\nChunks:\n";
        for (const auto& chunk : info.chunks) {
            std::cout << "  " << aether::package::chunkTypeName(chunk.type) << "  "
                      << chunk.uncompressedBytes << " bytes"
                      << (chunk.compression == aether::package::Compression::zstd ? " (zstd)" : "")
                      << (chunk.required ? " required" : " optional") << '\n';
        }
        if (canonicalManifest)
            std::cout << "Canonical asset: " << canonicalManifest->name << " (" << canonicalCameras
                      << " cameras, " << canonicalConfidenceValues << " confidence values, metres, "
                      << canonicalManifest->coordinateSystem << ")\n";
    }
    return 0;
}

int main(int argc, char** argv) noexcept {
    const bool json = requestsJson(argc, argv);
    try {
        return run(argc, argv);
    } catch (const std::exception& error) {
        if (json)
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                       "package inspection failure\"}}\n",
                       stderr);
        else
            std::fprintf(stderr, "Unhandled package inspection failure: %s\n", error.what());
    } catch (...) {
        if (json)
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"Unhandled "
                       "package inspection failure\"}}\n",
                       stderr);
        else
            std::fputs("Unhandled package inspection failure\n", stderr);
    }
    return 5;
}
