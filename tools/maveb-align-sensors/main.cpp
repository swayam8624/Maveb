#include <aether/capture/RecordedSequenceSource.hpp>
#include <aether/package/Sha256.hpp>
#include <aether/reconstruction/ColmapCameraRig.hpp>
#include <aether/reconstruction/SensorAlignment.hpp>

#include <simdjson.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

using aether::reconstruction::AlignmentCameraPose;
using aether::reconstruction::CameraPoseCorrespondence;
using aether::reconstruction::ColmapCameraRecord;
using aether::reconstruction::SensorAlignmentConfig;
using aether::reconstruction::SensorAlignmentResult;

constexpr std::uintmax_t maximumMappingBytes = 16ULL * 1024ULL * 1024ULL;

struct Options final {
    std::filesystem::path colmapModel;
    std::filesystem::path capture;
    std::filesystem::path matches;
    std::filesystem::path output;
    SensorAlignmentConfig alignment;
    bool dryRun{};
    bool json{};
};

struct Match final {
    std::string colmapImage;
    std::uint64_t captureFrameId{};
};

std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size());
    constexpr char hexadecimal[] = "0123456789abcdef";
    for (const char raw : value) {
        const auto character = static_cast<unsigned char>(raw);
        switch (character) {
        case '"':
            result += "\\\"";
            break;
        case '\\':
            result += "\\\\";
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
            if (character < 0x20U) {
                result += "\\u00";
                result += hexadecimal[(character >> 4U) & 0x0fU];
                result += hexadecimal[character & 0x0fU];
            } else {
                result += static_cast<char>(character);
            }
        }
    }
    return result;
}

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"sensor-alignment-error\","
                     "\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

int usage() {
    std::cout << "Usage: maveb-align-sensors <colmap-text-model> <capture.mavebcapture>\n"
                 "       --matches <camera-matches.json> --output <metric-camera-rig.json>\n"
                 "       [--position-inlier <metres>] [--orientation-inlier <degrees>]\n"
                 "       [--minimum-inliers <count>] [--minimum-inlier-ratio <ratio>]\n"
                 "       [--seed <integer>] [--dry-run] [--json]\n\n"
                 "Fits a robust COLMAP-to-iPad metric Sim(3), verifies the complete capture "
                 "package, and\n"
                 "writes every registered COLMAP camera in the metric capture frame. The match "
                 "file uses\n"
                 "schemaVersion 1 and pairs of colmapImage plus captureFrameId.\n";
    return 0;
}

template <typename Value> std::optional<Value> parseNumber(std::string_view text) {
    std::istringstream stream{std::string(text)};
    stream.imbue(std::locale::classic());
    Value value{};
    if (!(stream >> value))
        return std::nullopt;
    stream >> std::ws;
    if (!stream.eof())
        return std::nullopt;
    return value;
}

std::optional<Options> parseOptions(int argc, char** argv, int& exitCode) {
    Options options;
    for (int index = 1; index < argc; ++index)
        if (std::string_view(argv[index]) == "--json")
            options.json = true;
    std::vector<std::filesystem::path> positional;
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
        } else if (argument == "--matches" || argument == "--output" ||
                   argument == "--position-inlier" || argument == "--orientation-inlier" ||
                   argument == "--minimum-inliers" || argument == "--minimum-inlier-ratio" ||
                   argument == "--seed") {
            if (++index >= argc) {
                exitCode = fail(std::string(argument) + " requires a value", options.json);
                return std::nullopt;
            }
            const std::string_view value(argv[index]);
            if (argument == "--matches")
                options.matches = value;
            else if (argument == "--output")
                options.output = value;
            else if (argument == "--position-inlier") {
                auto parsed = parseNumber<double>(value);
                if (!parsed) {
                    exitCode = fail("--position-inlier is invalid", options.json);
                    return std::nullopt;
                }
                options.alignment.positionInlierThresholdMetres = *parsed;
            } else if (argument == "--orientation-inlier") {
                auto parsed = parseNumber<double>(value);
                if (!parsed) {
                    exitCode = fail("--orientation-inlier is invalid", options.json);
                    return std::nullopt;
                }
                options.alignment.orientationInlierThresholdDegrees = *parsed;
            } else if (argument == "--minimum-inliers") {
                auto parsed = parseNumber<std::size_t>(value);
                if (!parsed) {
                    exitCode = fail("--minimum-inliers is invalid", options.json);
                    return std::nullopt;
                }
                options.alignment.minimumInliers = *parsed;
            } else if (argument == "--minimum-inlier-ratio") {
                auto parsed = parseNumber<double>(value);
                if (!parsed) {
                    exitCode = fail("--minimum-inlier-ratio is invalid", options.json);
                    return std::nullopt;
                }
                options.alignment.minimumInlierRatio = *parsed;
            } else {
                auto parsed = parseNumber<std::uint64_t>(value);
                if (!parsed) {
                    exitCode = fail("--seed is invalid", options.json);
                    return std::nullopt;
                }
                options.alignment.deterministicSeed = *parsed;
            }
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else {
            positional.emplace_back(argument);
        }
    }
    if (positional.size() != 2 || options.matches.empty() || options.output.empty()) {
        exitCode = fail("Two inputs, --matches, and --output are required", options.json);
        return std::nullopt;
    }
    options.colmapModel = positional[0];
    options.capture = positional[1];
    if (options.output.extension() != ".json") {
        exitCode = fail("Metric camera-rig output must use the .json extension", options.json);
        return std::nullopt;
    }
    return options;
}

aether::Result<std::vector<Match>> loadMatches(const std::filesystem::path& path,
                                               std::size_t maximumMatches) {
    std::error_code error;
    const auto bytes = std::filesystem::file_size(path, error);
    if (error || bytes == 0 || bytes > maximumMappingBytes)
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Camera match file is missing, empty, or too large", path);
    std::vector<char> json(static_cast<std::size_t>(maximumMappingBytes) +
                           simdjson::SIMDJSON_PADDING);
    std::ifstream stream(path, std::ios::binary);
    stream.read(json.data(), static_cast<std::streamsize>(bytes));
    if (stream.gcount() != static_cast<std::streamsize>(bytes))
        return aether::fail(aether::ErrorCode::io, "Unable to read camera match file", path);
    simdjson::dom::parser parser(maximumMappingBytes);
    if (parser.allocate(maximumMappingBytes))
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Unable to allocate bounded camera match parser");
    simdjson::dom::element root;
    if (parser.parse(json.data(), static_cast<std::size_t>(bytes), false).get(root))
        return aether::fail(aether::ErrorCode::corruptData, "Camera match JSON is malformed", path);
    std::uint64_t schemaVersion{};
    simdjson::dom::array pairs;
    if (root["schemaVersion"].get(schemaVersion) || schemaVersion != 1 ||
        root["pairs"].get_array().get(pairs))
        return aether::fail(aether::ErrorCode::corruptData,
                            "Camera match schema must be version 1 with a pairs array", path);
    std::vector<Match> result;
    result.reserve(std::min<std::size_t>(pairs.size(), maximumMatches));
    std::unordered_set<std::string> images;
    std::unordered_set<std::uint64_t> frameIds;
    for (auto pair : pairs) {
        std::string_view image;
        std::uint64_t frameId{};
        if (pair["colmapImage"].get(image) || pair["captureFrameId"].get(frameId) ||
            image.empty() || frameId == 0 || result.size() >= maximumMatches)
            return aether::fail(aether::ErrorCode::corruptData,
                                "Camera match pair is invalid or exceeds its limit", path);
        const std::filesystem::path imagePath(image);
        if (imagePath.is_absolute() ||
            std::ranges::any_of(imagePath, [](const auto& component) { return component == ".."; }))
            return aether::fail(aether::ErrorCode::corruptData,
                                "Matched COLMAP image must be a safe relative path", path);
        std::string imageName(image);
        if (!images.insert(imageName).second || !frameIds.insert(frameId).second)
            return aether::fail(aether::ErrorCode::corruptData, "Camera matches must be one-to-one",
                                path);
        result.push_back(Match{std::move(imageName), frameId});
    }
    return result;
}

aether::Result<std::unordered_map<std::uint64_t, AlignmentCameraPose>>
loadCapturePoses(const std::filesystem::path& capture) {
    auto source = aether::capture::RecordedSequenceSource::open(capture);
    if (!source)
        return std::unexpected(source.error());
    std::unordered_map<std::uint64_t, AlignmentCameraPose> poses;
    (*source)->setPacketCallback([&](aether::capture::CapturePacket packet) {
        if (packet.cameraToWorld)
            poses.emplace(packet.frameId, AlignmentCameraPose{packet.cameraToWorld->translation,
                                                              packet.cameraToWorld->orientation});
    });
    auto started = (*source)->start();
    if (!started)
        return std::unexpected(started.error());
    while (true) {
        auto stepped = (*source)->step();
        if (!stepped) {
            const auto& stepError = stepped.error();
            auto stopped = (*source)->stop();
            if (!stopped)
                return std::unexpected(stopped.error());
            return std::unexpected(stepError);
        }
        if (!*stepped)
            break;
    }
    auto stopped = (*source)->stop();
    if (!stopped)
        return std::unexpected(stopped.error());
    if (poses.size() != (*source)->frameCount())
        return aether::fail(aether::ErrorCode::corruptData,
                            "Capture does not provide one valid pose per frame", capture);
    return poses;
}

aether::Result<aether::package::Sha256Digest> hashFile(const std::filesystem::path& path) {
    std::error_code error;
    const auto bytes = std::filesystem::file_size(path, error);
    if (error || bytes == 0)
        return aether::fail(aether::ErrorCode::io, "Unable to size provenance input", path);
    std::ifstream stream(path, std::ios::binary);
    aether::package::Sha256 hash;
    std::vector<std::byte> buffer(std::size_t{1024} * 1024);
    std::uintmax_t remaining = bytes;
    while (remaining > 0) {
        const auto amount = static_cast<std::size_t>(
            std::min<std::uintmax_t>(remaining, static_cast<std::uintmax_t>(buffer.size())));
        stream.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(amount));
        if (stream.gcount() != static_cast<std::streamsize>(amount))
            return aether::fail(aether::ErrorCode::io, "Unable to hash provenance input", path);
        hash.update(std::span<const std::byte>(buffer.data(), amount));
        remaining -= amount;
    }
    return hash.finalize();
}

void writePose(std::ostringstream& output, const AlignmentCameraPose& pose) {
    output << "{\"translation\":[" << pose.position[0] << ',' << pose.position[1] << ','
           << pose.position[2] << "],\"orientationWxyz\":[" << pose.orientation[0] << ','
           << pose.orientation[1] << ',' << pose.orientation[2] << ',' << pose.orientation[3]
           << "]}";
}

std::string buildReport(const Options& options, const std::vector<ColmapCameraRecord>& cameras,
                        const std::vector<Match>& matches,
                        const std::vector<CameraPoseCorrespondence>& correspondences,
                        const SensorAlignmentResult& alignment,
                        const aether::package::Sha256Digest& colmapHash,
                        const aether::package::Sha256Digest& captureManifestHash,
                        const aether::package::Sha256Digest& matchesHash) {
    std::unordered_set<std::size_t> inliers(alignment.inlierIndices.begin(),
                                            alignment.inlierIndices.end());
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    output << "{\"schemaVersion\":1,\"accepted\":" << (alignment.accepted ? "true" : "false")
           << ",\"coordinateContract\":{\"source\":\"COLMAP arbitrary scale, camera axes +X "
              "right +Y down +Z forward\",\"target\":\"Maveb metric capture world, camera axes "
              "+X right +Y down +Z forward\"},\"provenance\":{\"colmapImagesSha256\":\""
           << aether::package::Sha256::hex(colmapHash) << "\",\"captureManifestSha256\":\""
           << aether::package::Sha256::hex(captureManifestHash) << "\",\"matchesSha256\":\""
           << aether::package::Sha256::hex(matchesHash)
           << "\",\"seed\":" << options.alignment.deterministicSeed
           << "},\"transform\":{\"scale\":" << alignment.sourceToMetricTarget.scale
           << ",\"orientationWxyz\":[" << alignment.sourceToMetricTarget.orientation[0] << ','
           << alignment.sourceToMetricTarget.orientation[1] << ','
           << alignment.sourceToMetricTarget.orientation[2] << ','
           << alignment.sourceToMetricTarget.orientation[3] << "],\"translationMetres\":["
           << alignment.sourceToMetricTarget.translation[0] << ','
           << alignment.sourceToMetricTarget.translation[1] << ','
           << alignment.sourceToMetricTarget.translation[2]
           << "]},\"metrics\":{\"correspondences\":" << alignment.metrics.correspondences
           << ",\"inliers\":" << alignment.metrics.inliers
           << ",\"inlierRatio\":" << alignment.metrics.inlierRatio
           << ",\"positionRmseMetres\":" << alignment.metrics.positionRmseMetres
           << ",\"positionMedianMetres\":" << alignment.metrics.positionMedianMetres
           << ",\"positionP95Metres\":" << alignment.metrics.positionP95Metres
           << ",\"positionMaximumMetres\":" << alignment.metrics.positionMaximumMetres
           << ",\"orientationMedianDegrees\":" << alignment.metrics.orientationMedianDegrees
           << ",\"orientationP95Degrees\":" << alignment.metrics.orientationP95Degrees
           << ",\"orientationMaximumDegrees\":" << alignment.metrics.orientationMaximumDegrees
           << "},\"issues\":[";
    for (std::size_t index = 0; index < alignment.issues.size(); ++index) {
        if (index > 0)
            output << ',';
        output << '"' << escapeJson(alignment.issues[index]) << '"';
    }
    output << "],\"correspondences\":[";
    for (std::size_t index = 0; index < correspondences.size(); ++index) {
        if (index > 0)
            output << ',';
        output << "{\"colmapImage\":\"" << escapeJson(matches[index].colmapImage)
               << "\",\"captureFrameId\":" << matches[index].captureFrameId
               << ",\"inlier\":" << (inliers.contains(index) ? "true" : "false")
               << ",\"positionResidualMetres\":" << alignment.positionResidualsMetres[index]
               << ",\"orientationResidualDegrees\":" << alignment.orientationResidualsDegrees[index]
               << '}';
    }
    output << "],\"metricCameras\":[";
    for (std::size_t index = 0; index < cameras.size(); ++index) {
        if (index > 0)
            output << ',';
        output << "{\"imageId\":" << cameras[index].imageId
               << ",\"cameraId\":" << cameras[index].cameraId << ",\"imageName\":\""
               << escapeJson(cameras[index].imageName) << "\",\"cameraToMetricWorld\":";
        writePose(output,
                  alignment.sourceToMetricTarget.transformCamera(cameras[index].cameraToWorld));
        output << '}';
    }
    output << "]}\n";
    return output.str();
}

aether::Result<void> writeAtomic(const std::filesystem::path& destination,
                                 std::string_view contents) {
    std::error_code error;
    if (!destination.parent_path().empty())
        std::filesystem::create_directories(destination.parent_path(), error);
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to create output directory",
                            destination.parent_path());
    auto temporary = destination;
    temporary += ".tmp";
    std::filesystem::remove(temporary, error);
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(contents.data(), static_cast<std::streamsize>(contents.size()));
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to write alignment report", destination);
    }
    std::filesystem::rename(temporary, destination, error);
    if (error) {
        std::filesystem::remove(temporary, error);
        return aether::fail(aether::ErrorCode::io, "Unable to publish alignment report atomically",
                            destination);
    }
    return {};
}

int run(int argc, char** argv) {
    int parseExitCode{};
    auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;
    auto cameras = aether::reconstruction::loadColmapCameraRig(options->colmapModel / "images.txt");
    if (!cameras)
        return fail(cameras.error().describe(), options->json, 3);
    auto matches = loadMatches(options->matches, options->alignment.maximumCorrespondences);
    if (!matches)
        return fail(matches.error().describe(), options->json, 3);
    auto capturePoses = loadCapturePoses(options->capture);
    if (!capturePoses)
        return fail(capturePoses.error().describe(), options->json, 3);
    std::unordered_map<std::string, const ColmapCameraRecord*> camerasByName;
    for (const auto& camera : *cameras)
        camerasByName.emplace(camera.imageName, &camera);
    std::vector<CameraPoseCorrespondence> correspondences;
    correspondences.reserve(matches->size());
    for (const auto& match : *matches) {
        const auto camera = camerasByName.find(match.colmapImage);
        const auto target = capturePoses->find(match.captureFrameId);
        if (camera == camerasByName.end() || target == capturePoses->end())
            return fail("Camera match references a missing COLMAP image or capture frame",
                        options->json, 3);
        correspondences.push_back(
            CameraPoseCorrespondence{match.colmapImage + "#" + std::to_string(match.captureFrameId),
                                     camera->second->cameraToWorld, target->second});
    }
    auto alignment = aether::reconstruction::alignCameraRigs(correspondences, options->alignment);
    if (!alignment)
        return fail(alignment.error().describe(), options->json, 4);
    auto colmapHash = hashFile(options->colmapModel / "images.txt");
    auto captureHash = hashFile(options->capture / "manifest.json");
    auto matchesHash = hashFile(options->matches);
    if (!colmapHash || !captureHash || !matchesHash)
        return fail("Unable to hash complete sensor-alignment provenance", options->json, 4);
    const auto report = buildReport(*options, *cameras, *matches, correspondences, *alignment,
                                    *colmapHash, *captureHash, *matchesHash);
    if (!options->dryRun) {
        auto written = writeAtomic(options->output, report);
        if (!written)
            return fail(written.error().describe(), options->json, 4);
    }
    const auto digest = aether::package::Sha256::hex(
        aether::package::Sha256::hash(std::as_bytes(std::span(report.data(), report.size()))));
    if (options->json)
        std::cout << "{\"ok\":true,\"accepted\":" << (alignment->accepted ? "true" : "false")
                  << ",\"dryRun\":" << (options->dryRun ? "true" : "false") << ",\"output\":\""
                  << escapeJson(options->output.string()) << "\",\"sha256\":\"" << digest
                  << "\",\"cameras\":" << cameras->size()
                  << ",\"correspondences\":" << alignment->metrics.correspondences
                  << ",\"inliers\":" << alignment->metrics.inliers
                  << ",\"positionP95Metres\":" << alignment->metrics.positionP95Metres
                  << ",\"orientationP95Degrees\":" << alignment->metrics.orientationP95Degrees
                  << "}\n";
    else
        std::cout << (alignment->accepted ? "Accepted" : "Rejected") << " metric alignment with "
                  << alignment->metrics.inliers << '/' << alignment->metrics.correspondences
                  << " inlier cameras\n";
    return alignment->accepted ? 0 : 6;
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
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":"
                       "\"Unhandled sensor alignment failure\"}}\n",
                       stderr);
        else
            std::fprintf(stderr, "Unhandled sensor alignment failure: %s\n", error.what());
    } catch (...) {
        if (json)
            std::fputs("{\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":"
                       "\"Unhandled sensor alignment failure\"}}\n",
                       stderr);
        else
            std::fputs("Unhandled sensor alignment failure\n", stderr);
    }
    return 5;
}
