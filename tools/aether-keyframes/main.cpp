#include <aether/capture/CaptureValidator.hpp>
#include <aether/capture/KeyframeSelector.hpp>

#include <charconv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <string>
#include <string_view>

namespace {
struct Options final {
    std::filesystem::path input;
    std::filesystem::path output;
    aether::capture::KeyframeSelectionOptions selection;
    bool dryRun{};
    bool json{};
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

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"keyframe-selection-error\","
                     "\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

int usage() {
    std::cout << "Usage: aether-keyframes <frames-directory> --output <selection-directory> "
                 "[--minimum-gap 2] [--maximum-gap 30] [--relative-sharpness 0.35] "
                 "[--minimum-change 0.015] [--maximum-change 0.65] [--dry-run] [--json]\n";
    return 0;
}

std::optional<std::size_t> parseSize(std::string_view value) {
    std::uint64_t parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed == 0 ||
        parsed > std::numeric_limits<std::size_t>::max())
        return std::nullopt;
    return static_cast<std::size_t>(parsed);
}

std::optional<double> parseDouble(std::string_view value) {
    double parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size())
        return std::nullopt;
    return parsed;
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
            continue;
        }
        if (argument == "--dry-run") {
            options.dryRun = true;
            continue;
        }
        auto value = [&]() -> std::optional<std::string_view> {
            if (++index >= argc) {
                exitCode = fail("Option requires a value: " + std::string(argument), options.json);
                return std::nullopt;
            }
            return std::string_view(argv[index]);
        };
        if (argument == "--output" || argument == "--minimum-gap" || argument == "--maximum-gap" ||
            argument == "--relative-sharpness" || argument == "--minimum-change" ||
            argument == "--maximum-change") {
            const auto supplied = value();
            if (!supplied)
                return std::nullopt;
            if (argument == "--output") {
                options.output = *supplied;
            } else if (argument == "--minimum-gap" || argument == "--maximum-gap") {
                const auto parsed = parseSize(*supplied);
                if (!parsed) {
                    exitCode = fail("Frame-gap value is invalid", options.json);
                    return std::nullopt;
                }
                if (argument == "--minimum-gap")
                    options.selection.minimumFrameGap = *parsed;
                else
                    options.selection.maximumFrameGap = *parsed;
            } else {
                const auto parsed = parseDouble(*supplied);
                if (!parsed) {
                    exitCode = fail("Selection threshold is invalid", options.json);
                    return std::nullopt;
                }
                if (argument == "--relative-sharpness")
                    options.selection.relativeSharpnessThreshold = *parsed;
                else if (argument == "--minimum-change")
                    options.selection.minimumAppearanceDistance = *parsed;
                else
                    options.selection.maximumAppearanceDistance = *parsed;
            }
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.input.empty()) {
            options.input = argument;
        } else {
            exitCode = fail("Only one frames directory may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.input.empty() || options.output.empty()) {
        exitCode = fail("Frames directory and --output are required", options.json);
        return std::nullopt;
    }
    return options;
}

std::filesystem::path relativeImage(const std::filesystem::path& path,
                                    const std::filesystem::path& root) {
    std::error_code error;
    auto relative = std::filesystem::relative(path, root, error);
    if (error)
        return path.filename();
    return relative;
}

bool writeOutputs(const Options& options, const aether::capture::CaptureReport& capture,
                  const aether::capture::KeyframeSelectionReport& selection) {
    std::error_code error;
    const auto temporaryDirectory = std::filesystem::path(options.output.string() + ".tmp");
    std::filesystem::remove_all(temporaryDirectory, error);
    error.clear();
    std::filesystem::create_directories(temporaryDirectory, error);
    if (error)
        return false;
    const auto listPath = temporaryDirectory / "selected-images.txt";
    std::ofstream list(listPath, std::ios::trunc);
    for (const auto& path : selection.selectedImages)
        list << relativeImage(path, options.input).generic_string() << '\n';
    list.close();
    if (!list) {
        std::filesystem::remove_all(temporaryDirectory);
        return false;
    }

    const auto manifestPath = temporaryDirectory / "keyframes.json";
    std::ofstream manifest(manifestPath, std::ios::trunc);
    manifest << "{\n  \"schemaVersion\":1,\n  \"input\":\"" << escapeJson(options.input.string())
             << "\",\n  \"candidateCount\":" << capture.images.size()
             << ",\n  \"selectedCount\":" << selection.selectedImages.size()
             << ",\n  \"valid\":" << (selection.valid() ? "true" : "false")
             << ",\n  \"configuration\":{\"minimumFrameGap\":" << options.selection.minimumFrameGap
             << ",\"maximumFrameGap\":" << options.selection.maximumFrameGap
             << ",\"relativeSharpnessThreshold\":" << options.selection.relativeSharpnessThreshold
             << ",\"minimumAppearanceDistance\":" << options.selection.minimumAppearanceDistance
             << ",\"maximumAppearanceDistance\":" << options.selection.maximumAppearanceDistance
             << "},\n  \"issues\":[";
    for (std::size_t index = 0; index < selection.issues.size(); ++index) {
        if (index > 0)
            manifest << ',';
        manifest << '"' << escapeJson(selection.issues[index]) << '"';
    }
    manifest << "],\n  \"frames\":[\n";
    for (std::size_t index = 0; index < selection.decisions.size(); ++index) {
        const auto& decision = selection.decisions[index];
        const auto& measurement = capture.images[index];
        manifest << "    {\"path\":\""
                 << escapeJson(relativeImage(decision.path, options.input).generic_string())
                 << "\",\"selected\":" << (decision.selected ? "true" : "false") << ",\"reason\":\""
                 << escapeJson(decision.reason)
                 << "\",\"appearanceDistance\":" << decision.appearanceDistance
                 << ",\"sharpness\":" << measurement.sharpness
                 << ",\"meanLuminance\":" << measurement.meanLuminance << '}'
                 << (index + 1 == selection.decisions.size() ? "\n" : ",\n");
    }
    manifest << "  ]\n}\n";
    manifest.close();
    if (!manifest) {
        std::filesystem::remove_all(temporaryDirectory);
        return false;
    }
    if (std::filesystem::exists(options.output, error)) {
        if (error ||
            renamex_np(temporaryDirectory.c_str(), options.output.c_str(), RENAME_SWAP) != 0) {
            std::filesystem::remove_all(temporaryDirectory);
            return false;
        }
        std::filesystem::remove_all(temporaryDirectory, error);
        return !error;
    }
    if (error) {
        std::filesystem::remove_all(temporaryDirectory);
        return false;
    }
    std::filesystem::rename(temporaryDirectory, options.output, error);
    if (error)
        std::filesystem::remove_all(temporaryDirectory);
    return !error;
}
} // namespace

int main(int argc, char** argv) {
    int parseExitCode = 0;
    const auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;
    aether::capture::ValidationOptions validation;
    validation.minimumImages = options->selection.minimumSelectedImages;
    validation.analysisMaximumDimension = 512;
    const auto capture = aether::capture::validateCapture(options->input, validation);
    const auto selection = aether::capture::selectKeyframes(capture, options->selection);
    if (!selection.valid()) {
        std::string message = "Keyframe selection failed";
        for (const auto& issue : selection.issues)
            message += " · " + issue;
        return fail(message, options->json, 3);
    }
    if (!options->dryRun && !writeOutputs(*options, capture, selection))
        return fail("Unable to write keyframe selection outputs", options->json, 4);
    if (options->json)
        std::cout << "{\"ok\":true,\"dryRun\":" << (options->dryRun ? "true" : "false")
                  << ",\"candidateCount\":" << capture.images.size()
                  << ",\"selectedCount\":" << selection.selectedImages.size() << ",\"imageList\":\""
                  << escapeJson((options->output / "selected-images.txt").string())
                  << "\",\"manifest\":\""
                  << escapeJson((options->output / "keyframes.json").string()) << "\"}\n";
    else
        std::cout << "Selected " << selection.selectedImages.size() << " of "
                  << capture.images.size() << " frames\n";
    return 0;
}
