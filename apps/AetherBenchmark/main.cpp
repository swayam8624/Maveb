#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/metal/GaussianPipeline.hpp>
#include <aether/metal/MetalPtr.hpp>
#include <aether/package/Package.hpp>
#include <aether/scene/Camera.hpp>
#include <aether/scene/CameraPath.hpp>

#include <Foundation/Foundation.hpp>
#include <Metal/Metal.hpp>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace {
struct Options final {
    std::filesystem::path scene;
    std::filesystem::path cameraPath;
    std::uint32_t width{1920};
    std::uint32_t height{1080};
    std::uint32_t frames{};
    std::uint32_t warmupFrames{5};
    bool json{};
    bool dryRun{};
    std::optional<double> maximumP95Milliseconds;
    std::optional<std::uint64_t> maximumAllocatedBytes;
};

std::string escapeJson(std::string_view value) {
    std::string result;
    for (const char character : value) {
        if (character == '\\')
            result += "\\\\";
        else if (character == '"')
            result += "\\\"";
        else if (character == '\n')
            result += "\\n";
        else
            result += character;
    }
    return result;
}

int usage() {
    std::cout << "Usage: aether-benchmark <scene.aether> --camera-path path.json "
                 "[--width 1920] [--height 1080] [--frames N] [--warmup N] [--json] "
                 "[--max-p95-ms N] [--max-memory-bytes N] [--dry-run]\n";
    return 0;
}

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"benchmark-error\",\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

std::optional<std::uint32_t> parseUnsigned(std::string_view value) {
    std::uint64_t parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed == 0 ||
        parsed > std::numeric_limits<std::uint32_t>::max())
        return std::nullopt;
    return static_cast<std::uint32_t>(parsed);
}

std::optional<std::uint64_t> parseUnsigned64(std::string_view value) {
    std::uint64_t parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed == 0)
        return std::nullopt;
    return parsed;
}

std::optional<double> parsePositiveDouble(std::string_view value) {
    double parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() ||
        !std::isfinite(parsed) || parsed <= 0.0)
        return std::nullopt;
    return parsed;
}

std::optional<Options> parseOptions(int argc, char** argv, int& exitCode) {
    Options options;
    for (int index = 1; index < argc; ++index)
        if (std::string_view(argv[index]) == "--json") options.json = true;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--help" || argument == "-h") {
            exitCode = usage();
            return std::nullopt;
        }
        if (argument == "--json") {
            options.json = true;
            continue;
        }
        if (argument == "--dry-run") {
            options.dryRun = true;
            continue;
        }
        auto readValue = [&](const char* name) -> std::optional<std::string_view> {
            if (++index >= argc) {
                exitCode = fail(std::string(name) + " requires a value", options.json);
                return std::nullopt;
            }
            return std::string_view(argv[index]);
        };
        if (argument == "--camera-path") {
            auto value = readValue("--camera-path");
            if (!value)
                return std::nullopt;
            options.cameraPath = *value;
        } else if (argument == "--max-p95-ms") {
            auto value = readValue("--max-p95-ms");
            if (!value || !(options.maximumP95Milliseconds = parsePositiveDouble(*value))) {
                exitCode = fail("--max-p95-ms must be finite and positive", options.json);
                return std::nullopt;
            }
        } else if (argument == "--max-memory-bytes") {
            auto value = readValue("--max-memory-bytes");
            if (!value || !(options.maximumAllocatedBytes = parseUnsigned64(*value))) {
                exitCode = fail("--max-memory-bytes must be a positive integer", options.json);
                return std::nullopt;
            }
        } else if (argument == "--width" || argument == "--height" || argument == "--frames" ||
                   argument == "--warmup") {
            auto value = readValue(std::string(argument).c_str());
            if (!value)
                return std::nullopt;
            auto number = parseUnsigned(*value);
            if (!number) {
                exitCode =
                    fail("Numeric option is invalid: " + std::string(argument), options.json);
                return std::nullopt;
            }
            if (argument == "--width")
                options.width = *number;
            else if (argument == "--height")
                options.height = *number;
            else if (argument == "--frames")
                options.frames = *number;
            else
                options.warmupFrames = *number;
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.scene.empty()) {
            options.scene = argument;
        } else {
            exitCode = fail("Only one scene package may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.scene.empty() || options.cameraPath.empty()) {
        exitCode = fail("Scene and --camera-path are required", options.json);
        return std::nullopt;
    }
    constexpr std::uint32_t maximumDimension = 16'384;
    if (options.width > maximumDimension || options.height > maximumDimension) {
        exitCode = fail("Benchmark dimensions exceed the safety limit", options.json);
        return std::nullopt;
    }
    return options;
}

aether::metal::MetalPtr<MTL::Texture> makeTarget(MTL::Device* device, MTL::PixelFormat format,
                                                 std::uint32_t width, std::uint32_t height,
                                                 const char* label) {
    auto descriptor = aether::metal::adopt(MTL::TextureDescriptor::alloc()->init());
    descriptor->setTextureType(MTL::TextureType2D);
    descriptor->setPixelFormat(format);
    descriptor->setWidth(width);
    descriptor->setHeight(height);
    descriptor->setStorageMode(MTL::StorageModePrivate);
    descriptor->setUsage(MTL::TextureUsageShaderWrite | MTL::TextureUsageShaderRead);
    auto texture = aether::metal::adopt(device->newTexture(descriptor.get()));
    if (texture)
        texture->setLabel(NS::String::string(label, NS::UTF8StringEncoding));
    return texture;
}

std::uint32_t entryBudget(std::size_t gaussianCount) {
    constexpr std::uint64_t maximum = 4'194'304;
    const std::uint64_t requested =
        gaussianCount > maximum / 64 ? maximum : static_cast<std::uint64_t>(gaussianCount) * 64;
    return static_cast<std::uint32_t>(std::clamp<std::uint64_t>(requested, 262'144, maximum));
}
} // namespace

int main(int argc, char** argv) {
    int parseExitCode = 0;
    auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;

    auto scenePackage = aether::package::PackageReader::open(options->scene);
    if (!scenePackage)
        return fail(scenePackage.error().describe(), options->json, 3);
    auto gaussianBytes = scenePackage->readChunk(aether::package::ChunkType::baseGaussians);
    if (!gaussianBytes)
        return fail(gaussianBytes.error().describe(), options->json, 3);
    auto asset = aether::gaussian::GaussianCodec::decode(*gaussianBytes);
    if (!asset)
        return fail(asset.error().describe(), options->json, 3);
    auto cameraPath = aether::scene::CameraPath::load(options->cameraPath);
    if (!cameraPath)
        return fail(cameraPath.error().describe(), options->json, 3);
    if (options->frames == 0) {
        options->frames = static_cast<std::uint32_t>(
            std::clamp(std::ceil(cameraPath->duration() * 60.0) + 1.0, 1.0, 100'000.0));
    }
    if (options->dryRun) {
        std::cout << (options->json ? "{\"ok\":true,\"dryRun\":true,\"gaussians\":"
                                    : "Validated benchmark. Gaussians: ")
                  << asset->gaussians.size();
        if (options->json)
            std::cout << ",\"frames\":" << options->frames << "}\n";
        else
            std::cout << ", frames: " << options->frames << '\n';
        return 0;
    }

    NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init();
    auto device = aether::metal::adopt(MTL::CreateSystemDefaultDevice());
    if (!device) {
        pool->release();
        return fail("No Metal device is available", options->json, 4);
    }
    NS::Error* libraryError = nullptr;
    auto library = aether::metal::adopt(device->newLibrary(
        NS::String::string(AETHER_BENCHMARK_SHADER_LIBRARY, NS::UTF8StringEncoding),
        &libraryError));
    if (!library) {
        const std::string message = libraryError
                                        ? libraryError->localizedDescription()->utf8String()
                                        : "Unable to load benchmark metallib";
        pool->release();
        return fail(message, options->json, 4);
    }
    auto pipeline = aether::metal::GaussianPipeline::create(device.get(), library.get(),
                                                            entryBudget(asset->gaussians.size()));
    if (!pipeline || !(*pipeline)->load(*asset)) {
        pool->release();
        return fail("Unable to create Gaussian benchmark pipeline", options->json, 4);
    }
    auto color = makeTarget(device.get(), MTL::PixelFormatRGBA16Float, options->width,
                            options->height, "Benchmark Gaussian Color");
    auto depth = makeTarget(device.get(), MTL::PixelFormatR32Float, options->width, options->height,
                            "Benchmark Gaussian Depth");
    auto ids = makeTarget(device.get(), MTL::PixelFormatR32Uint, options->width, options->height,
                          "Benchmark Gaussian IDs");
    auto queue = aether::metal::adopt(device->newCommandQueue());
    if (!color || !depth || !ids || !queue) {
        pool->release();
        return fail("Unable to allocate benchmark Metal resources", options->json, 4);
    }
    queue->setLabel(NS::String::string("AETHER Benchmark Queue", NS::UTF8StringEncoding));

    std::vector<double> gpuMilliseconds;
    std::vector<double> cpuFrameMilliseconds;
    gpuMilliseconds.reserve(options->frames);
    cpuFrameMilliseconds.reserve(options->frames);
    std::uint64_t peakAllocatedBytes = device->currentAllocatedSize();
    aether::metal::GaussianPipelineStatistics peakStatistics{};
    const std::uint64_t totalFrames =
        static_cast<std::uint64_t>(options->warmupFrames) + options->frames;
    for (std::uint64_t frame = 0; frame < totalFrames; ++frame) {
        const std::uint32_t measuredIndex =
            frame < options->warmupFrames
                ? 0U
                : static_cast<std::uint32_t>(frame - options->warmupFrames);
        const double amount = options->frames <= 1 ? 0.0
                                                   : static_cast<double>(measuredIndex) /
                                                         static_cast<double>(options->frames - 1);
        auto keyframe = cameraPath->sample(cameraPath->duration() * amount);
        if (!keyframe) {
            pool->release();
            return fail(keyframe.error().describe(), options->json, 4);
        }
        aether::scene::Camera sceneCamera;
        sceneCamera.verticalFieldOfViewRadians = keyframe->verticalFieldOfViewRadians;
        auto view = sceneCamera.viewMatrix(keyframe->transform);
        if (!view) {
            pool->release();
            return fail(view.error().describe(), options->json, 4);
        }
        simd_float4x4 positiveZView = *view;
        for (simd_float4& column : positiveZView.columns)
            column.z = -column.z;
        const float focal = static_cast<float>(options->height) /
                            (2.0F * std::tan(keyframe->verticalFieldOfViewRadians * 0.5F));
        AetherGaussianCamera camera{};
        camera.worldToCamera = positiveZView;
        camera.focalCenter = {focal, focal, static_cast<float>(options->width) * 0.5F,
                              static_cast<float>(options->height) * 0.5F};
        camera.depthViewport = {sceneCamera.nearPlane, 10'000.0F,
                                static_cast<float>(options->width),
                                static_cast<float>(options->height)};
        camera.cameraWorldPosition = {keyframe->transform.translation.x,
                                      keyframe->transform.translation.y,
                                      keyframe->transform.translation.z, 1.0F};
        const auto cpuFrameStart = std::chrono::steady_clock::now();
        MTL::CommandBuffer* commandBuffer = queue->commandBuffer();
        auto encoded =
            (*pipeline)->encode(commandBuffer, camera, color.get(), depth.get(), ids.get(), frame % 3);
        if (!commandBuffer || !encoded) {
            pool->release();
            return fail(encoded ? "Unable to allocate benchmark command buffer"
                                : encoded.error().describe(),
                        options->json, 4);
        }
        commandBuffer->setLabel(
            NS::String::string("AETHER Benchmark Frame", NS::UTF8StringEncoding));
        commandBuffer->commit();
        commandBuffer->waitUntilCompleted();
        if (commandBuffer->status() == MTL::CommandBufferStatusError) {
            pool->release();
            return fail("Benchmark Metal command buffer failed", options->json, 4);
        }
        if (frame >= options->warmupFrames) {
            gpuMilliseconds.push_back(
                (commandBuffer->GPUEndTime() - commandBuffer->GPUStartTime()) * 1000.0);
            cpuFrameMilliseconds.push_back(std::chrono::duration<double, std::milli>(
                                               std::chrono::steady_clock::now() - cpuFrameStart)
                                               .count());
        }
        peakAllocatedBytes =
            std::max<std::uint64_t>(peakAllocatedBytes, device->currentAllocatedSize());
        const auto statistics = (*pipeline)->statistics();
        peakStatistics.visibleGaussians =
            std::max(peakStatistics.visibleGaussians, statistics.visibleGaussians);
        peakStatistics.tileEntries = std::max(peakStatistics.tileEntries, statistics.tileEntries);
        peakStatistics.overflowedEntries =
            std::max(peakStatistics.overflowedEntries, statistics.overflowedEntries);
        peakStatistics.earlyTerminations =
            std::max(peakStatistics.earlyTerminations, statistics.earlyTerminations);
    }
    std::ranges::sort(gpuMilliseconds);
    std::ranges::sort(cpuFrameMilliseconds);
    if (peakStatistics.overflowedEntries != 0) {
        const std::string message = "Tile-entry budget overflowed by " +
                                    std::to_string(peakStatistics.overflowedEntries) +
                                    " entries; benchmark output would be incomplete";
        pool->release();
        return fail(message, options->json, 5);
    }
    const double median = gpuMilliseconds[gpuMilliseconds.size() / 2];
    const std::size_t p95Index = static_cast<std::size_t>(
        std::ceil(static_cast<double>(gpuMilliseconds.size()) * 0.95) - 1.0);
    const double p95 = gpuMilliseconds[std::min(p95Index, gpuMilliseconds.size() - 1)];
    const double cpuMedian = cpuFrameMilliseconds[cpuFrameMilliseconds.size() / 2];
    const double cpuP95 =
        cpuFrameMilliseconds[std::min(p95Index, cpuFrameMilliseconds.size() - 1)];
    const bool p95BudgetPassed = !options->maximumP95Milliseconds ||
                                 p95 <= *options->maximumP95Milliseconds;
    const bool memoryBudgetPassed = !options->maximumAllocatedBytes ||
                                    peakAllocatedBytes <= *options->maximumAllocatedBytes;
    const bool budgetsPassed = p95BudgetPassed && memoryBudgetPassed;
    const std::string deviceName = device->name() ? device->name()->utf8String() : "Unknown GPU";
    if (options->json) {
        std::cout << "{\"ok\":" << (budgetsPassed ? "true" : "false")
                  << ",\"schemaVersion\":2,\"device\":\"" << escapeJson(deviceName)
                  << "\",\"scene\":\"" << escapeJson(options->scene.string())
                  << "\",\"width\":" << options->width << ",\"height\":" << options->height
                  << ",\"frames\":" << options->frames
                  << ",\"warmupFrames\":" << options->warmupFrames << ",\"gpuMedianMs\":" << median
                  << ",\"gpuP95Ms\":" << p95 << ",\"cpuFrameMedianMs\":" << cpuMedian
                  << ",\"cpuFrameP95Ms\":" << cpuP95
                  << ",\"gaussians\":" << asset->gaussians.size()
                  << ",\"peakVisibleGaussians\":" << peakStatistics.visibleGaussians
                  << ",\"peakTileEntries\":" << peakStatistics.tileEntries
                  << ",\"peakOverflowedEntries\":" << peakStatistics.overflowedEntries
                  << ",\"peakEarlyTerminations\":" << peakStatistics.earlyTerminations
                  << ",\"peakMetalAllocatedBytes\":" << peakAllocatedBytes
                  << ",\"budgets\":{\"passed\":" << (budgetsPassed ? "true" : "false")
                  << ",\"p95Passed\":" << (p95BudgetPassed ? "true" : "false")
                  << ",\"memoryPassed\":" << (memoryBudgetPassed ? "true" : "false")
                  << "}}\n";
    } else {
        std::cout << "AETHER benchmark on " << deviceName << '\n'
                  << options->width << 'x' << options->height << ", " << options->frames
                  << " measured frames\nGPU median: " << median << " ms\nGPU p95: " << p95
                  << " ms\nCPU frame p95: " << cpuP95
                  << " ms\nPeak visible Gaussians: " << peakStatistics.visibleGaussians
                  << "\nPeak tile entries: " << peakStatistics.tileEntries
                  << "\nPeak Metal allocation: " << peakAllocatedBytes << " bytes\n"
                  << "Budgets: " << (budgetsPassed ? "passed" : "FAILED") << '\n';
    }
    pool->release();
    return budgetsPassed ? 0 : 6;
}
