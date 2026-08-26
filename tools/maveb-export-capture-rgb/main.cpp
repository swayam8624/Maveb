#include <aether/capture/RecordedSequenceSource.hpp>
#include <aether/package/Sha256.hpp>

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct Options final {
    std::filesystem::path capture;
    std::filesystem::path output;
    bool json{};
};

struct ImageRecord final {
    std::uint64_t frameId{};
    std::uint64_t presentationTimestampNs{};
    std::uint64_t hostTimestampNs{};
    std::string file;
    std::string sha256;
    std::uint32_t width{};
    std::uint32_t height{};
};

struct DecodedImage final {
    std::uint32_t width{};
    std::uint32_t height{};
    std::vector<std::uint8_t> rgb;
};

std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size());
    constexpr char hexadecimal[] = "0123456789abcdef";
    for (const char raw : value) {
        const auto character = static_cast<unsigned char>(raw);
        switch (character) {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
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
        std::cerr << "{\"ok\":false,\"error\":\"" << escapeJson(message) << "\"}\n";
    else
        std::cerr << "maveb-export-capture-rgb: " << message << '\n';
    return code;
}

int usage() {
    std::cout << "Usage: maveb-export-capture-rgb <capture.mavebcapture> --output <images-directory> [--json]\n\n"
                 "Replays a versioned recorded capture, verifies its recorded plane hashes, and exports\n"
                 "deterministic PNG RGB frames plus rgb-export.json provenance. Existing output paths\n"
                 "are never overwritten. Native recorded pixel order is preserved; no orientation or\n"
                 "mirroring transform is applied.\n";
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
        if (argument == "--json")
            continue;
        if (argument == "--output") {
            if (++index >= argc) {
                exitCode = fail("--output requires a value", options.json);
                return std::nullopt;
            }
            options.output = argv[index];
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.capture.empty()) {
            options.capture = argument;
        } else {
            exitCode = fail("Only one capture directory may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.capture.empty() || options.output.empty()) {
        exitCode = fail("Capture directory and --output are required", options.json);
        return std::nullopt;
    }
    return options;
}

std::string fileSha256(const std::filesystem::path& path) {
    aether::package::Sha256 hash;
    std::array<std::byte, 1024 * 1024> buffer{};
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        return {};
    while (stream) {
        stream.read(reinterpret_cast<char*>(buffer.data()),
                    static_cast<std::streamsize>(buffer.size()));
        const auto count = stream.gcount();
        if (count > 0)
            hash.update(std::span<const std::byte>(buffer.data(), static_cast<std::size_t>(count)));
    }
    if (!stream.eof())
        return {};
    return aether::package::Sha256::hex(hash.finalize());
}

std::uint8_t quantize(double value) {
    const auto scaled = std::clamp(value, 0.0, 1.0) * 255.0;
    return static_cast<std::uint8_t>(std::lround(scaled));
}

std::optional<DecodedImage> decodeColor(const aether::capture::CapturePacket& packet,
                                        std::string& error) {
    if (packet.colorPlanes.empty()) {
        error = "Recorded packet has no color plane";
        return std::nullopt;
    }
    const auto& first = packet.colorPlanes.front();
    if (!first.valid() || first.width == 0 || first.height == 0) {
        error = "Recorded packet color plane is invalid";
        return std::nullopt;
    }

    DecodedImage decoded;
    decoded.width = first.width;
    decoded.height = first.height;
    decoded.rgb.resize(static_cast<std::size_t>(decoded.width) * decoded.height * 3);

    for (std::uint32_t y = 0; y < decoded.height; ++y) {
        const auto* sourceRow = first.buffer.data + static_cast<std::size_t>(y) * first.rowStrideBytes;
        auto* targetRow = decoded.rgb.data() + static_cast<std::size_t>(y) * decoded.width * 3;
        if (first.format == aether::capture::PixelFormat::rgb8) {
            std::copy_n(reinterpret_cast<const std::uint8_t*>(sourceRow),
                        static_cast<std::size_t>(decoded.width) * 3, targetRow);
            continue;
        }
        if (first.format == aether::capture::PixelFormat::gray8) {
            for (std::uint32_t x = 0; x < decoded.width; ++x) {
                const auto value = std::to_integer<std::uint8_t>(sourceRow[x]);
                targetRow[x * 3 + 0] = value;
                targetRow[x * 3 + 1] = value;
                targetRow[x * 3 + 2] = value;
            }
            continue;
        }
        if (first.format == aether::capture::PixelFormat::bgra8) {
            for (std::uint32_t x = 0; x < decoded.width; ++x) {
                const auto* pixel = sourceRow + static_cast<std::size_t>(x) * 4;
                targetRow[x * 3 + 0] = std::to_integer<std::uint8_t>(pixel[2]);
                targetRow[x * 3 + 1] = std::to_integer<std::uint8_t>(pixel[1]);
                targetRow[x * 3 + 2] = std::to_integer<std::uint8_t>(pixel[0]);
            }
            continue;
        }
        if (first.format != aether::capture::PixelFormat::yuv420BiPlanarVideoRange ||
            packet.colorPlanes.size() != 2) {
            error = "Recorded packet color format is unsupported";
            return std::nullopt;
        }
        const auto& chroma = packet.colorPlanes[1];
        if (!chroma.valid() || chroma.format != aether::capture::PixelFormat::yuv420BiPlanarVideoRange ||
            chroma.width * 2 != decoded.width || chroma.height * 2 != decoded.height) {
            error = "Recorded YUV chroma plane is invalid";
            return std::nullopt;
        }
        const auto* chromaRow = chroma.buffer.data + static_cast<std::size_t>(y / 2) * chroma.rowStrideBytes;
        for (std::uint32_t x = 0; x < decoded.width; ++x) {
            const auto luma = std::to_integer<std::uint8_t>(sourceRow[x]);
            const auto* chromaPixel = chromaRow + static_cast<std::size_t>(x / 2) * 2;
            const auto cbRaw = std::to_integer<std::uint8_t>(chromaPixel[0]);
            const auto crRaw = std::to_integer<std::uint8_t>(chromaPixel[1]);
            const double yy = std::clamp((static_cast<double>(luma) - 16.0) / 219.0, 0.0, 1.0);
            const double cb = (static_cast<double>(cbRaw) - 128.0) / 224.0;
            const double cr = (static_cast<double>(crRaw) - 128.0) / 224.0;
            targetRow[x * 3 + 0] = quantize(yy + 1.5748 * cr);
            targetRow[x * 3 + 1] = quantize(yy - 0.1873 * cb - 0.4681 * cr);
            targetRow[x * 3 + 2] = quantize(yy + 1.8556 * cb);
        }
    }
    return decoded;
}

bool writePng(const std::filesystem::path& path, const DecodedImage& image) {
    auto colourSpace = CGColorSpaceCreateDeviceRGB();
    auto provider = CGDataProviderCreateWithData(nullptr, image.rgb.data(), image.rgb.size(), nullptr);
    auto cgImage = CGImageCreate(image.width, image.height, 8, 24,
                                 static_cast<std::size_t>(image.width) * 3, colourSpace,
                                 kCGImageAlphaNone, provider, nullptr, false,
                                 kCGRenderingIntentDefault);
    const auto pathString = path.string();
    auto url = CFURLCreateFromFileSystemRepresentation(
        nullptr, reinterpret_cast<const UInt8*>(pathString.data()),
        static_cast<CFIndex>(pathString.size()), false);
    auto destination = url && cgImage
                           ? CGImageDestinationCreateWithURL(url, CFSTR("public.png"), 1, nullptr)
                           : nullptr;
    if (destination)
        CGImageDestinationAddImage(destination, cgImage, nullptr);
    const bool written = destination && CGImageDestinationFinalize(destination);
    if (destination)
        CFRelease(destination);
    if (url)
        CFRelease(url);
    if (cgImage)
        CGImageRelease(cgImage);
    if (provider)
        CGDataProviderRelease(provider);
    if (colourSpace)
        CGColorSpaceRelease(colourSpace);
    return written;
}

std::string frameFilename(std::uint64_t frameId) {
    std::ostringstream stream;
    stream << "frame-" << std::setw(6) << std::setfill('0') << frameId << ".png";
    return stream.str();
}

bool writeManifest(const std::filesystem::path& path, std::string_view sourceId,
                   std::string_view captureManifestSha256,
                   const std::vector<ImageRecord>& records) {
    std::ofstream stream(path, std::ios::trunc);
    if (!stream)
        return false;
    stream << "{\n"
              "  \"schemaVersion\": 1,\n"
              "  \"generator\": \"maveb-export-capture-rgb\",\n"
              "  \"sourceID\": \"" << escapeJson(sourceId) << "\",\n"
              "  \"captureManifestSha256\": \"" << captureManifestSha256 << "\",\n"
              "  \"pixelTransform\": \"none; native recorded pixel order preserved\",\n"
              "  \"frameCount\": " << records.size() << ",\n"
              "  \"images\": [\n";
    for (std::size_t index = 0; index < records.size(); ++index) {
        const auto& record = records[index];
        stream << "    {\"frameID\":" << record.frameId
               << ",\"presentationTimestampNs\":" << record.presentationTimestampNs
               << ",\"hostTimestampNs\":" << record.hostTimestampNs
               << ",\"file\":\"" << escapeJson(record.file)
               << "\",\"sha256\":\"" << record.sha256
               << "\",\"width\":" << record.width
               << ",\"height\":" << record.height << "}"
               << (index + 1 == records.size() ? "\n" : ",\n");
    }
    stream << "  ]\n}\n";
    return static_cast<bool>(stream);
}

} // namespace

int main(int argc, char** argv) {
    int parseExitCode = 0;
    const auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;

    std::error_code error;
    if (std::filesystem::exists(options->output, error) || error)
        return fail("Output path already exists or cannot be inspected", options->json);
    const auto temporary = std::filesystem::path(options->output.string() + ".tmp");
    if (std::filesystem::exists(temporary, error) || error)
        return fail("Temporary output path already exists", options->json);
    if (!std::filesystem::create_directories(temporary, error) || error)
        return fail("Unable to create output directory", options->json, 3);

    const auto cleanup = [&]() {
        std::error_code ignored;
        std::filesystem::remove_all(temporary, ignored);
    };

    auto source = aether::capture::RecordedSequenceSource::open(options->capture);
    if (!source) {
        cleanup();
        return fail(source.error().describe(), options->json, 3);
    }
    std::vector<ImageRecord> records;
    std::optional<std::string> pipelineError;
    (*source)->setPacketCallback([&](const aether::capture::CapturePacket& packet) {
        if (pipelineError)
            return;
        std::string decodeError;
        auto decoded = decodeColor(packet, decodeError);
        if (!decoded) {
            pipelineError = decodeError;
            return;
        }
        const auto filename = frameFilename(packet.frameId);
        const auto outputPath = temporary / filename;
        if (!writePng(outputPath, *decoded)) {
            pipelineError = "Unable to encode PNG for frame " + std::to_string(packet.frameId);
            return;
        }
        const auto digest = fileSha256(outputPath);
        if (digest.empty()) {
            pipelineError = "Unable to hash exported PNG for frame " + std::to_string(packet.frameId);
            return;
        }
        records.push_back(ImageRecord{packet.frameId, packet.presentationTimestampNs,
                                      packet.hostTimestampNs, filename, digest,
                                      decoded->width, decoded->height});
    });

    auto info = (*source)->start();
    if (!info) {
        cleanup();
        return fail(info.error().describe(), options->json, 3);
    }
    while (true) {
        auto stepped = (*source)->step();
        if (!stepped) {
            [[maybe_unused]] const auto stopped = (*source)->stop();
            cleanup();
            return fail(stepped.error().describe(), options->json, 3);
        }
        if (!*stepped || pipelineError)
            break;
    }
    auto stopped = (*source)->stop();
    if (!stopped) {
        cleanup();
        return fail(stopped.error().describe(), options->json, 3);
    }
    if (pipelineError) {
        cleanup();
        return fail(*pipelineError, options->json, 3);
    }
    if (records.size() != (*source)->frameCount()) {
        cleanup();
        return fail("Exported frame count differs from recorded frame count", options->json, 3);
    }

    const auto captureManifestSha = fileSha256(options->capture / "manifest.json");
    if (captureManifestSha.empty() ||
        !writeManifest(temporary / "rgb-export.json", info->sourceId,
                       captureManifestSha, records)) {
        cleanup();
        return fail("Unable to write RGB export provenance", options->json, 3);
    }

    std::filesystem::rename(temporary, options->output, error);
    if (error) {
        cleanup();
        return fail("Unable to finalize RGB export directory", options->json, 3);
    }

    if (options->json)
        std::cout << "{\"ok\":true,\"frames\":" << records.size()
                  << ",\"output\":\"" << escapeJson(options->output.string())
                  << "\",\"manifest\":\""
                  << escapeJson((options->output / "rgb-export.json").string()) << "\"}\n";
    else
        std::cout << "Exported " << records.size() << " recorded RGB frames to "
                  << options->output << '\n';
    return 0;
}
