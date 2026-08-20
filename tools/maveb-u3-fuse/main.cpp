#include <aether/capture/CapturePacket.hpp>
#include <aether/core/Error.hpp>
#include <aether/mesh/PlyExporter.hpp>
#include <aether/reconstruction/ReconstructionContracts.hpp>
#include <aether/reconstruction/UncertaintyTsdfVolume.hpp>

#include <simdjson.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#if defined(__APPLE__) || defined(__linux__)
#include <sys/resource.h>
#endif

namespace {

using aether::capture::CapturePacket;
using aether::capture::ImagePlane;
using aether::capture::PixelFormat;
using aether::reconstruction::DepthObservation;
using aether::reconstruction::MetricUncertaintyFusionConfig;
using aether::reconstruction::PoseEstimate;
using aether::reconstruction::TsdfFusionWeighting;
using aether::reconstruction::UncertaintyTsdfConfig;
using aether::reconstruction::UncertaintyTsdfVolume;

struct Options final {
    std::filesystem::path manifest;
    std::filesystem::path output;
    std::string mode;
    bool json{};
};

struct FrameSpec final {
    std::uint64_t frameId{};
    std::uint64_t timestampNanoseconds{};
    std::uint32_t width{};
    std::uint32_t height{};
    std::array<double, 4> intrinsics{};
    std::array<double, 4> quaternion{};
    std::array<double, 3> translation{};
    std::filesystem::path depthPath;
    std::filesystem::path confidencePath;
    std::filesystem::path shuffledConfidencePath;
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
    if (argc < 2)
        return std::nullopt;
    Options options;
    options.manifest = argv[1];
    for (int index = 2; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--mode" && index + 1 < argc) {
            options.mode = argv[++index];
        } else if (argument == "--output" && index + 1 < argc) {
            options.output = argv[++index];
        } else if (argument == "--json") {
            options.json = true;
        } else {
            return std::nullopt;
        }
    }
    if (options.mode.empty() || options.output.empty() || options.output.extension() != ".ply")
        return std::nullopt;
    const std::array<std::string_view, 5> modes{
        "uniform",
        "naive-confidence",
        "calibrated-depth-only",
        "calibrated-inverse-variance",
        "calibrated-shuffled-confidence",
    };
    bool known = false;
    for (const auto mode : modes)
        known = known || options.mode == mode;
    return known ? std::optional<Options>(options) : std::nullopt;
}

void printHelp() {
    std::cerr << "Usage: maveb-u3-fuse <scene-manifest.json> --mode <uniform|naive-confidence|"
                 "calibrated-depth-only|calibrated-inverse-variance|"
                 "calibrated-shuffled-confidence> --output <mesh.ply> [--json]\n";
}

std::string stringField(simdjson::dom::element object, const char* field) {
    std::string_view value;
    if (object[field].get(value))
        throw std::runtime_error(std::string("invalid string field: ") + field);
    return std::string(value);
}

double numberField(simdjson::dom::element object, const char* field) {
    double value{};
    if (object[field].get(value) || !std::isfinite(value))
        throw std::runtime_error(std::string("invalid numeric field: ") + field);
    return value;
}

std::uint64_t uintField(simdjson::dom::element object, const char* field) {
    std::uint64_t value{};
    if (object[field].get(value))
        throw std::runtime_error(std::string("invalid integer field: ") + field);
    return value;
}

template <std::size_t Size>
std::array<double, Size> numberArray(simdjson::dom::element object, const char* field) {
    simdjson::dom::array values;
    if (object[field].get_array().get(values) || values.size() != Size)
        throw std::runtime_error(std::string("invalid numeric array: ") + field);
    std::array<double, Size> result{};
    std::size_t index = 0;
    for (auto value : values) {
        if (value.get(result[index]) || !std::isfinite(result[index]))
            throw std::runtime_error(std::string("non-finite numeric array: ") + field);
        ++index;
    }
    return result;
}

template <std::size_t Size>
std::array<std::uint32_t, Size> uintArray(simdjson::dom::element object, const char* field) {
    simdjson::dom::array values;
    if (object[field].get_array().get(values) || values.size() != Size)
        throw std::runtime_error(std::string("invalid integer array: ") + field);
    std::array<std::uint32_t, Size> result{};
    std::size_t index = 0;
    for (auto value : values) {
        std::uint64_t parsed{};
        if (value.get(parsed) || parsed > std::numeric_limits<std::uint32_t>::max())
            throw std::runtime_error(std::string("out-of-range integer array: ") + field);
        result[index++] = static_cast<std::uint32_t>(parsed);
    }
    return result;
}

std::vector<std::byte> readBytes(const std::filesystem::path& path, std::size_t expectedBytes) {
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    if (error || size != expectedBytes)
        throw std::runtime_error("unexpected file size: " + path.string());
    std::vector<std::byte> bytes(expectedBytes);
    std::ifstream stream(path, std::ios::binary);
    if (!stream.read(reinterpret_cast<char*>(bytes.data()),
                     static_cast<std::streamsize>(bytes.size())))
        throw std::runtime_error("unable to read: " + path.string());
    return bytes;
}

std::uint64_t peakResidentBytes() {
#if defined(__APPLE__) || defined(__linux__)
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) != 0)
        return 0;
#if defined(__APPLE__)
    return static_cast<std::uint64_t>(usage.ru_maxrss);
#else
    return static_cast<std::uint64_t>(usage.ru_maxrss) * 1024ULL;
#endif
#else
    return 0;
#endif
}

TsdfFusionWeighting weightingForMode(std::string_view mode) {
    if (mode == "uniform")
        return TsdfFusionWeighting::uniform;
    if (mode == "naive-confidence")
        return TsdfFusionWeighting::naiveConfidence;
    return TsdfFusionWeighting::calibratedInverseVariance;
}

} // namespace

int main(int argc, char** argv) { // NOLINT(bugprone-exception-escape)
    const auto options = parseOptions(argc, argv);
    if (!options) {
        printHelp();
        return 2;
    }

    try {
        simdjson::dom::parser parser;
        auto loaded = parser.load(options->manifest.string());
        if (loaded.error())
            throw std::runtime_error("unable to parse U3 scene manifest");
        simdjson::dom::element document = loaded.value();
        if (uintField(document, "schemaVersion") != 1 ||
            stringField(document, "study") != "metric-uncertainty-u3-dense-tsdf-v1")
            throw std::runtime_error("unsupported U3 scene manifest");
        const auto scene = stringField(document, "scene");
        if (stringField(document, "cameraConvention") != "+X right, +Y down, +Z forward" ||
            stringField(document, "poseConvention") !=
                "camera-to-world in FARO laser-scanner coordinates")
            throw std::runtime_error("U3 scene coordinate convention is unsupported");

        simdjson::dom::element volumeObject;
        if (document["volume"].get(volumeObject))
            throw std::runtime_error("U3 scene volume is missing");
        aether::reconstruction::DenseTsdfConfig dense;
        dense.originMetres = numberArray<3>(volumeObject, "originMetres");
        dense.dimensions = uintArray<3>(volumeObject, "dimensions");
        dense.voxelSizeMetres = numberField(volumeObject, "voxelSizeMetres");
        dense.truncationDistanceMetres = numberField(volumeObject, "truncationDistanceMetres");
        dense.minimumDepthMetres = numberField(volumeObject, "minimumDepthMetres");
        dense.maximumDepthMetres = numberField(volumeObject, "maximumDepthMetres");
        dense.maximumWeight = numberField(volumeObject, "maximumWeight");

        simdjson::dom::element uncertaintyObject;
        if (document["uncertainty"].get(uncertaintyObject))
            throw std::runtime_error("U3 uncertainty configuration is missing");
        MetricUncertaintyFusionConfig uncertainty;
        uncertainty.minimumSigmaMetres = numberField(uncertaintyObject, "minimumSigmaMetres");
        uncertainty.maximumSigmaMetres = numberField(uncertaintyObject, "maximumSigmaMetres");
        uncertainty.depthNoiseFloorMetres = numberField(uncertaintyObject, "depthNoiseFloorMetres");
        uncertainty.depthNoiseQuadraticMetresPerMetreSquared =
            numberField(uncertaintyObject, "depthNoiseQuadraticMetresPerMetreSquared");
        uncertainty.sensorConfidencePenalty =
            numberField(uncertaintyObject, "sensorConfidencePenalty");
        uncertainty.poseTranslationFloorMetres =
            numberField(uncertaintyObject, "poseTranslationFloorMetres");
        uncertainty.poseTranslationScaleMetres =
            numberField(uncertaintyObject, "poseTranslationScaleMetres");
        uncertainty.referenceSigmaMetres = numberField(uncertaintyObject, "referenceSigmaMetres");
        uncertainty.minimumPrecisionWeight =
            numberField(uncertaintyObject, "minimumPrecisionWeight");
        uncertainty.maximumPrecisionWeight =
            numberField(uncertaintyObject, "maximumPrecisionWeight");
        if (options->mode == "calibrated-depth-only")
            uncertainty.sensorConfidencePenalty = 0.0;

        UncertaintyTsdfConfig config;
        config.volume = dense;
        config.weighting = weightingForMode(options->mode);
        config.uncertainty = uncertainty;
        auto volume = UncertaintyTsdfVolume::create(config);
        if (!volume)
            throw std::runtime_error(volume.error().describe());

        simdjson::dom::array frameObjects;
        if (document["frames"].get_array().get(frameObjects) || frameObjects.size() == 0)
            throw std::runtime_error("U3 scene has no frames");
        std::vector<FrameSpec> frames;
        frames.reserve(frameObjects.size());
        const auto root = options->manifest.parent_path();
        for (auto frameObject : frameObjects) {
            FrameSpec frame;
            frame.frameId = uintField(frameObject, "frameId");
            frame.timestampNanoseconds = uintField(frameObject, "timestampNanoseconds");
            const auto width = uintField(frameObject, "width");
            const auto height = uintField(frameObject, "height");
            if (width == 0 || height == 0 || width > std::numeric_limits<std::uint32_t>::max() ||
                height > std::numeric_limits<std::uint32_t>::max())
                throw std::runtime_error("U3 frame dimensions are invalid");
            frame.width = static_cast<std::uint32_t>(width);
            frame.height = static_cast<std::uint32_t>(height);
            frame.intrinsics = numberArray<4>(frameObject, "intrinsics");
            frame.quaternion = numberArray<4>(frameObject, "poseQuaternionWxyz");
            frame.translation = numberArray<3>(frameObject, "poseTranslationMetres");
            frame.depthPath = root / stringField(frameObject, "depthPath");
            frame.confidencePath = root / stringField(frameObject, "confidencePath");
            frame.shuffledConfidencePath =
                root / stringField(frameObject, "shuffledConfidencePath");
            frames.push_back(std::move(frame));
        }

        const auto started = std::chrono::steady_clock::now();
        std::size_t zeroUpdateFramesSkipped = 0;
        for (const auto& frame : frames) {
            const auto pixelCount = static_cast<std::size_t>(frame.width) * frame.height;
            auto depthBytes = readBytes(frame.depthPath, pixelCount * sizeof(float));
            const auto& confidencePath = options->mode == "calibrated-shuffled-confidence"
                                             ? frame.shuffledConfidencePath
                                             : frame.confidencePath;
            auto confidenceBytes = readBytes(confidencePath, pixelCount);

            CapturePacket packet;
            packet.frameId = frame.frameId;
            packet.sourceId = scene;
            packet.sourceKind = aether::capture::CaptureSourceKind::lidar;
            packet.presentationTimestampNs = frame.timestampNanoseconds;
            packet.hostTimestampNs = frame.timestampNanoseconds;
            packet.calibration.id = scene;
            packet.calibration.width = frame.width;
            packet.calibration.height = frame.height;
            packet.calibration.fx = frame.intrinsics[0];
            packet.calibration.fy = frame.intrinsics[1];
            packet.calibration.cx = frame.intrinsics[2];
            packet.calibration.cy = frame.intrinsics[3];
            packet.cameraToWorld = aether::capture::RigidPose{frame.quaternion, frame.translation};
            packet.depthMetres = ImagePlane{
                aether::capture::makeOwnedBuffer(std::move(depthBytes)),
                PixelFormat::depthFloat32Metres,
                frame.width,
                frame.height,
                frame.width * static_cast<std::uint32_t>(sizeof(float)),
            };
            packet.depthConfidence = ImagePlane{
                aether::capture::makeOwnedBuffer(std::move(confidenceBytes)),
                PixelFormat::confidenceUInt8,
                frame.width,
                frame.height,
                frame.width,
            };

            PoseEstimate pose{*packet.cameraToWorld, 1.0, 0, 0.0, true};
            DepthObservation depth{*packet.depthMetres, &*packet.depthConfidence, 1.0, 0.0,
                                   "ca1m-u3-frozen"};
            auto integrated = volume->integrate(packet, pose, depth);
            if (!integrated) {
                const auto& error = integrated.error();
                if (error.code == aether::ErrorCode::invalidArgument &&
                    error.message ==
                        "Depth frame did not observe any voxel in the configured volume") {
                    ++zeroUpdateFramesSkipped;
                    continue;
                }
                throw std::runtime_error(error.describe());
            }
        }

        if (volume->integratedFrames() == 0)
            throw std::runtime_error("U3 scene produced no updating frames");

        auto mesh = volume->extractMesh();
        if (!mesh)
            throw std::runtime_error(mesh.error().describe());
        std::error_code directoryError;
        if (!options->output.parent_path().empty())
            std::filesystem::create_directories(options->output.parent_path(), directoryError);
        if (directoryError)
            throw std::runtime_error("unable to create U3 mesh output directory");
        auto exported = aether::mesh::exportToPly(*mesh, options->output);
        if (!exported)
            throw std::runtime_error(exported.error().describe());
        const auto finished = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration<double, std::milli>(finished - started).count();
        const auto vertices = mesh->vertexCount();
        const auto triangles = mesh->indexCount() / 3;
        const auto resident = peakResidentBytes();

        if (options->json) {
            std::cout << "{\"ok\":true,\"scene\":\"" << jsonEscape(scene) << "\",\"method\":\""
                      << jsonEscape(options->mode) << "\",\"requestedFrames\":" << frames.size()
                      << ",\"frames\":" << volume->integratedFrames()
                      << ",\"zeroUpdateFramesSkipped\":" << zeroUpdateFramesSkipped
                      << ",\"vertices\":" << vertices << ",\"triangles\":" << triangles
                      << ",\"elapsedMilliseconds\":" << elapsed
                      << ",\"peakResidentBytes\":" << resident << ",\"output\":\""
                      << jsonEscape(options->output.string()) << "\"}\n";
        } else {
            std::cout << "U3 " << options->mode << ": " << vertices << " vertices, " << triangles
                      << " triangles, " << elapsed << " ms, " << zeroUpdateFramesSkipped
                      << " zero-update frames skipped\n";
        }
        return 0;
    } catch (const std::exception& error) {
        if (options->json)
            std::cerr << "{\"ok\":false,\"error\":\"" << jsonEscape(error.what()) << "\"}\n";
        else
            std::cerr << "maveb-u3-fuse: " << error.what() << '\n';
        return 1;
    }
}
