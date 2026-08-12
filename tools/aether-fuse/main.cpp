#include <aether/capture/RecordedSequenceSource.hpp>
#include <aether/mesh/GltfExporter.hpp>
#include <aether/mesh/PlyExporter.hpp>
#include <aether/reconstruction/DenseTsdfVolume.hpp>
#include <aether/reconstruction/RecordedProviders.hpp>

#include <array>
#include <charconv>
#include <concepts>
#include <filesystem>
#include <iostream>
#include <locale>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace {

struct Options final {
    std::filesystem::path capture;
    std::filesystem::path output;
    aether::reconstruction::DenseTsdfConfig volume;
    aether::reconstruction::DenseTsdfBoundsConfig bounds;
    bool json{};
    bool dryRun{};
    bool autoBounds{};
};

void printHelp() {
    std::cout << "Usage: aether-fuse <capture-directory> --output <proxy.ply|proxy.glb> "
                 "[options]\n"
                 "\n"
                 "Deterministically fuses schema-v1 RGB-D or schema-v2 MavebCapture "
                 "LiDAR\n"
                 "with recorded metric poses.\n"
                 "\n"
                 "Options:\n"
                 "  --origin X Y Z       volume origin in metres\n"
                 "  --dimensions X Y Z   dense reference volume dimensions\n"
                 "  --voxel METRES       voxel edge length\n"
                 "  --truncation METRES  TSDF truncation distance\n"
                 "  --auto-bounds        derive robust world bounds from recorded "
                 "depth\n"
                 "  --max-axis VOXELS    maximum dimension used by automatic bounds\n"
                 "  --sample-stride PX   depth sampling stride used by automatic "
                 "bounds\n"
                 "  --padding METRES     surface padding used by automatic bounds\n"
                 "  --dry-run            validate inputs without integrating\n"
                 "  --json               machine-readable result or error\n"
                 "  --help               show this help\n";
}

template <typename Number> bool parseNumber(std::string_view text, Number& value) {
    if constexpr (std::integral<Number>) {
        const auto* begin = text.data();
        const auto* end = text.data() + text.size();
        const auto result = std::from_chars(begin, end, value);
        return result.ec == std::errc{} && result.ptr == end;
    } else {
        std::istringstream stream{std::string(text)};
        stream.imbue(std::locale::classic());
        stream >> std::noskipws >> value;
        return stream && stream.eof();
    }
}

std::optional<Options> parseOptions(int argc, char** argv) {
    if (argc < 2)
        return std::nullopt;
    Options options;
    options.capture = argv[1];
    for (int index = 2; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--output" && index + 1 < argc) {
            options.output = argv[++index];
        } else if (argument == "--origin" && index + 3 < argc) {
            for (std::size_t axis = 0; axis < 3; ++axis)
                if (!parseNumber(argv[++index], options.volume.originMetres[axis]))
                    return std::nullopt;
        } else if (argument == "--dimensions" && index + 3 < argc) {
            for (std::size_t axis = 0; axis < 3; ++axis)
                if (!parseNumber(argv[++index], options.volume.dimensions[axis]))
                    return std::nullopt;
        } else if (argument == "--voxel" && index + 1 < argc) {
            if (!parseNumber(argv[++index], options.volume.voxelSizeMetres))
                return std::nullopt;
        } else if (argument == "--truncation" && index + 1 < argc) {
            if (!parseNumber(argv[++index], options.volume.truncationDistanceMetres))
                return std::nullopt;
        } else if (argument == "--auto-bounds") {
            options.autoBounds = true;
        } else if (argument == "--max-axis" && index + 1 < argc) {
            if (!parseNumber(argv[++index], options.bounds.maximumAxisVoxels))
                return std::nullopt;
        } else if (argument == "--sample-stride" && index + 1 < argc) {
            if (!parseNumber(argv[++index], options.bounds.pixelStride))
                return std::nullopt;
        } else if (argument == "--padding" && index + 1 < argc) {
            if (!parseNumber(argv[++index], options.bounds.paddingMetres))
                return std::nullopt;
        } else if (argument == "--json") {
            options.json = true;
        } else if (argument == "--dry-run") {
            options.dryRun = true;
        } else {
            return std::nullopt;
        }
    }
    if (options.output.empty() && !options.dryRun)
        return std::nullopt;
    if (!options.output.empty() && options.output.extension() != ".ply" &&
        options.output.extension() != ".glb")
        return std::nullopt;
    options.bounds.minimumVoxelSizeMetres = options.volume.voxelSizeMetres;
    return options;
}

int fail(const aether::Error& error, bool json) {
    if (json) {
        std::cerr << "{\"ok\":false,\"code\":" << static_cast<int>(error.code) << ",\"message\":\""
                  << error.message << "\",\"context\":\"" << error.context << "\"}\n";
    } else {
        std::cerr << "aether-fuse: " << error.describe() << '\n';
    }
    return 1;
}

} // namespace

int main(int argc, char** argv) { // NOLINT(bugprone-exception-escape)
    if (argc == 2 && std::string_view(argv[1]) == "--help") {
        printHelp();
        return 0;
    }
    auto options = parseOptions(argc, argv);
    if (!options) {
        printHelp();
        return 2;
    }

    auto source = aether::capture::RecordedSequenceSource::open(options->capture);
    if (!source)
        return fail(source.error(), options->json);
    std::optional<aether::reconstruction::DenseTsdfBoundsResult> automaticBounds;
    if (options->autoBounds) {
        auto estimator = aether::reconstruction::DenseTsdfBoundsEstimator::create(options->bounds);
        if (!estimator)
            return fail(estimator.error(), options->json);
        aether::reconstruction::RecordedPoseProvider poses;
        aether::reconstruction::RecordedRgbdDepthProvider depths;
        std::optional<aether::Error> boundsError;
        (*source)->setPacketCallback([&](const aether::capture::CapturePacket& packet) {
            if (boundsError)
                return;
            auto pose = poses.estimate(packet);
            if (!pose) {
                boundsError = pose.error();
                return;
            }
            auto depth = depths.estimate(packet, *pose);
            if (!depth) {
                boundsError = depth.error();
                return;
            }
            auto observed = estimator->observe(packet, *pose, *depth);
            if (!observed)
                boundsError = observed.error();
        });
        auto started = (*source)->start();
        if (!started)
            return fail(started.error(), options->json);
        while (true) {
            auto stepped = (*source)->step();
            if (!stepped) {
                [[maybe_unused]] const auto stopped = (*source)->stop();
                return fail(stepped.error(), options->json);
            }
            if (!*stepped || boundsError)
                break;
        }
        auto stopped = (*source)->stop();
        if (!stopped)
            return fail(stopped.error(), options->json);
        if (boundsError)
            return fail(*boundsError, options->json);
        auto estimatedBounds = estimator->estimate();
        if (!estimatedBounds)
            return fail(estimatedBounds.error(), options->json);
        automaticBounds = *estimatedBounds;
        options->volume = automaticBounds->volume;
        source = aether::capture::RecordedSequenceSource::open(options->capture);
        if (!source)
            return fail(source.error(), options->json);
    }
    auto volume = aether::reconstruction::DenseTsdfVolume::create(options->volume);
    if (!volume)
        return fail(volume.error(), options->json);
    if (options->dryRun) {
        if (options->json) {
            std::cout << "{\"ok\":true,\"dryRun\":true,\"frames\":" << (*source)->frameCount();
            if (automaticBounds) {
                const auto& config = automaticBounds->volume;
                std::cout << ",\"automaticBounds\":true,\"sampledPoints\":"
                          << automaticBounds->sampledPoints << ",\"origin\":["
                          << config.originMetres[0] << ',' << config.originMetres[1] << ','
                          << config.originMetres[2] << "],\"dimensions\":[" << config.dimensions[0]
                          << ',' << config.dimensions[1] << ',' << config.dimensions[2]
                          << "],\"voxelSizeMetres\":" << config.voxelSizeMetres
                          << ",\"truncationDistanceMetres\":" << config.truncationDistanceMetres;
            }
            std::cout << "}\n";
        } else
            std::cout << "Validated " << (*source)->frameCount() << " recorded frames\n";
        return 0;
    }

    aether::reconstruction::RecordedPoseProvider poses;
    aether::reconstruction::RecordedRgbdDepthProvider depths;
    std::optional<aether::Error> pipelineError;
    (*source)->setPacketCallback([&](const aether::capture::CapturePacket& packet) {
        if (pipelineError)
            return;
        auto pose = poses.estimate(packet);
        if (!pose) {
            pipelineError = pose.error();
            return;
        }
        auto depth = depths.estimate(packet, *pose);
        if (!depth) {
            pipelineError = depth.error();
            return;
        }
        auto integrated = volume->integrate(packet, *pose, *depth);
        if (!integrated)
            pipelineError = integrated.error();
    });
    auto started = (*source)->start();
    if (!started)
        return fail(started.error(), options->json);
    while (true) {
        auto stepped = (*source)->step();
        if (!stepped) {
            [[maybe_unused]] const auto stopped = (*source)->stop();
            return fail(stepped.error(), options->json);
        }
        if (!*stepped || pipelineError)
            break;
    }
    auto stopped = (*source)->stop();
    if (!stopped)
        return fail(stopped.error(), options->json);
    if (pipelineError)
        return fail(*pipelineError, options->json);
    auto mesh = volume->extractMesh();
    if (!mesh)
        return fail(mesh.error(), options->json);
    std::error_code directoryError;
    const auto parent = options->output.parent_path();
    if (!parent.empty())
        std::filesystem::create_directories(parent, directoryError);
    if (directoryError)
        return fail(aether::Error{aether::ErrorCode::io, "Unable to create mesh output directory",
                                  parent.string()},
                    options->json);
    const bool glbOutput = options->output.extension() == ".glb";
    auto exported = glbOutput ? aether::mesh::GltfExporter::writeStatic(*mesh, options->output)
                              : aether::mesh::exportToPly(*mesh, options->output);
    if (!exported)
        return fail(exported.error(), options->json);

    const auto vertices = mesh->vertexCount();
    const auto triangles = mesh->indexCount() / 3;
    if (options->json) {
        std::cout << "{\"ok\":true,\"frames\":" << volume->integratedFrames()
                  << ",\"vertices\":" << vertices << ",\"triangles\":" << triangles
                  << ",\"format\":\"" << (glbOutput ? "glb" : "ply") << "\""
                  << ",\"output\":\"" << options->output.string() << "\""
                  << ",\"origin\":[" << options->volume.originMetres[0] << ','
                  << options->volume.originMetres[1] << ',' << options->volume.originMetres[2]
                  << "],\"dimensions\":[" << options->volume.dimensions[0] << ','
                  << options->volume.dimensions[1] << ',' << options->volume.dimensions[2]
                  << "],\"voxelSizeMetres\":" << options->volume.voxelSizeMetres
                  << ",\"truncationDistanceMetres\":" << options->volume.truncationDistanceMetres
                  << "}\n";
    } else {
        std::cout << "Fused " << volume->integratedFrames() << " frames into " << vertices
                  << " vertices and " << triangles << " triangles\n"
                  << "Wrote " << options->output << '\n';
    }
    return 0;
}
