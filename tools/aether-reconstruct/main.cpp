#include <aether/core/Error.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/package/Sha256.hpp>
#include <aether/reconstruction/ReconstructionInput.hpp>
#include <aether/reconstruction/SparseModelValidator.hpp>

#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <charconv>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <set>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

extern char** environ;

namespace {
std::atomic<pid_t> activeChild{-1};

void interruptChild(int) {
    const pid_t child = activeChild.load(std::memory_order_relaxed);
    if (child > 0)
        (void)kill(child, SIGINT);
}

struct Options final {
    std::filesystem::path dataset;
    std::filesystem::path output;
    std::string colmap{"colmap"};
    std::string brush{"brush"};
    std::string proxy{"aether-proxy"};
    std::filesystem::path proxyConfig;
    std::filesystem::path imageList;
    std::filesystem::path preprocessingManifest;
    std::filesystem::path cameraGroups;
    aether::reconstruction::ReconstructionInputKind inputKind{
        aether::reconstruction::ReconstructionInputKind::unorderedPhotos};
    aether::reconstruction::MatcherStrategy matcher{
        aether::reconstruction::MatcherStrategy::exhaustive};
    aether::reconstruction::CameraGroupingMode cameraGrouping{
        aether::reconstruction::CameraGroupingMode::singleCamera};
    std::optional<aether::reconstruction::CameraGroupManifest> cameraGroupManifest;
    std::uint32_t sequentialOverlap{10};
    bool matcherExplicit{};
    bool cameraGroupingExplicit{};
    std::uint32_t seed{42};
    std::uint32_t steps{30'000};
    std::uint32_t checkpointEvery{5'000};
    std::string testProfile;
    bool json{};
    bool dryRun{};
};

struct Stage final {
    std::string name;
    std::vector<std::string> arguments;
    std::filesystem::path expectedOutput;
    std::filesystem::path requiredCompanion{};
};

struct InputImage final {
    std::filesystem::path path;
    std::uintmax_t bytes{};
    std::string sha256;
};

struct CheckpointRecovery final {
    std::filesystem::path path;
    std::uint32_t iteration{};
    std::size_t rejectedNewerCheckpoints{};
};

struct SparseSelectionEvidence final {
    std::vector<aether::reconstruction::SparseModelCandidate> candidates;
    std::optional<std::size_t> selectedIndex;
    std::string reason;
};

aether::Result<InputImage> hashInputImage(const std::filesystem::path& path,
                                          const std::filesystem::path& root);

void hashText(aether::package::Sha256& hash, std::string_view text) {
    hash.update(
        std::span<const std::byte>(reinterpret_cast<const std::byte*>(text.data()), text.size()));
    constexpr std::array separator{std::byte{0}};
    hash.update(separator);
}

aether::Result<std::string> jobFingerprint(const Options& options,
                                           const std::vector<InputImage>& inputs) {
    aether::package::Sha256 hash;
    hashText(hash, "aether-reconstruction-resume-v2");
    hashText(hash, aether::reconstruction::toString(options.inputKind));
    hashText(hash, aether::reconstruction::toString(options.matcher));
    hashText(hash, aether::reconstruction::toString(options.cameraGrouping));
    hashText(hash, std::to_string(options.sequentialOverlap));
    hashText(hash, std::to_string(options.seed));
    hashText(hash, std::to_string(options.steps));
    hashText(hash, std::to_string(options.checkpointEvery));
    for (const auto& input : inputs) {
        hashText(hash, input.path.generic_string());
        hashText(hash, std::to_string(input.bytes));
        hashText(hash, input.sha256);
    }
    if (!options.proxyConfig.empty()) {
        auto config = hashInputImage(options.proxyConfig, options.proxyConfig.parent_path());
        if (!config)
            return std::unexpected(config.error());
        hashText(hash, config->sha256);
    } else {
        hashText(hash, "default-proxy-config-v1");
    }
    const auto hashConfigurationFile = [&](const std::filesystem::path& path,
                                           std::string_view defaultValue) -> aether::Result<void> {
        if (path.empty()) {
            hashText(hash, defaultValue);
            return {};
        }
        auto input = hashInputImage(path, path.parent_path());
        if (!input)
            return std::unexpected(input.error());
        hashText(hash, input->path.generic_string());
        hashText(hash, input->sha256);
        return {};
    };
    if (auto result = hashConfigurationFile(options.imageList, "all-discovered-images-v1"); !result)
        return std::unexpected(result.error());
    if (auto result =
            hashConfigurationFile(options.preprocessingManifest, "no-preprocessing-manifest-v1");
        !result)
        return std::unexpected(result.error());
    if (auto result = hashConfigurationFile(options.cameraGroups, "single-camera-group-v1");
        !result)
        return std::unexpected(result.error());
    return aether::package::Sha256::hex(hash.finalize());
}

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

std::string commandDisplay(const std::vector<std::string>& arguments) {
    std::string result;
    for (const auto& argument : arguments) {
        if (!result.empty())
            result += ' ';
        const bool quote = argument.find_first_of(" \t\"'") != std::string::npos;
        if (quote)
            result += '"';
        for (const char character : argument) {
            if (character == '"' || character == '\\')
                result += '\\';
            result += character;
        }
        if (quote)
            result += '"';
    }
    return result;
}

int usage() {
    std::cout
        << "Usage: aether-reconstruct <dataset> --output <job-directory> "
           "[--trainer brush] [--colmap PATH] [--brush PATH] [--proxy PATH] "
           "[--proxy-config FILE] [--input-kind photos|video|multi-camera] "
           "[--matcher auto|exhaustive|sequential] "
           "[--camera-mode auto|single|per-folder|per-image] "
           "[--camera-groups FILE] [--image-list FILE] "
           "[--preprocessing-manifest FILE] [--sequential-overlap 10] [--seed 42] "
           "[--steps 30000] [--checkpoint-every 5000] [--test-profile NAME] [--dry-run] [--json]\n";
    return 0;
}

int fail(std::string_view message, bool json, int code = 2) {
    if (json)
        std::cerr << "{\"ok\":false,\"error\":{\"code\":\"reconstruction-error\","
                     "\"message\":\""
                  << escapeJson(message) << "\"}}\n";
    else
        std::cerr << message << '\n';
    return code;
}

std::optional<std::uint32_t> parsePositive(std::string_view value) {
    std::uint64_t parsed{};
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed == 0 ||
        parsed > std::numeric_limits<std::uint32_t>::max())
        return std::nullopt;
    return static_cast<std::uint32_t>(parsed);
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
        if (argument == "--output" || argument == "--colmap" || argument == "--brush" ||
            argument == "--proxy" || argument == "--proxy-config" || argument == "--trainer" ||
            argument == "--seed" || argument == "--steps" || argument == "--checkpoint-every" ||
            argument == "--test-profile" || argument == "--input-kind" || argument == "--matcher" ||
            argument == "--camera-mode" || argument == "--camera-groups" ||
            argument == "--image-list" || argument == "--preprocessing-manifest" ||
            argument == "--sequential-overlap") {
            auto supplied = value();
            if (!supplied)
                return std::nullopt;
            if (argument == "--output")
                options.output = *supplied;
            else if (argument == "--colmap")
                options.colmap = *supplied;
            else if (argument == "--brush")
                options.brush = *supplied;
            else if (argument == "--proxy")
                options.proxy = *supplied;
            else if (argument == "--proxy-config")
                options.proxyConfig = *supplied;
            else if (argument == "--camera-groups")
                options.cameraGroups = *supplied;
            else if (argument == "--image-list")
                options.imageList = *supplied;
            else if (argument == "--preprocessing-manifest")
                options.preprocessingManifest = *supplied;
            else if (argument == "--test-profile")
                options.testProfile = *supplied;
            else if (argument == "--input-kind") {
                if (*supplied == "photos")
                    options.inputKind =
                        aether::reconstruction::ReconstructionInputKind::unorderedPhotos;
                else if (*supplied == "video")
                    options.inputKind = aether::reconstruction::ReconstructionInputKind::video;
                else if (*supplied == "multi-camera")
                    options.inputKind =
                        aether::reconstruction::ReconstructionInputKind::multiCamera;
                else {
                    exitCode =
                        fail("Input kind must be photos, video, or multi-camera", options.json);
                    return std::nullopt;
                }
            } else if (argument == "--matcher") {
                options.matcherExplicit = *supplied != "auto";
                if (*supplied == "exhaustive")
                    options.matcher = aether::reconstruction::MatcherStrategy::exhaustive;
                else if (*supplied == "sequential")
                    options.matcher = aether::reconstruction::MatcherStrategy::sequential;
                else if (*supplied != "auto") {
                    exitCode =
                        fail("Matcher must be auto, exhaustive, or sequential", options.json);
                    return std::nullopt;
                }
            } else if (argument == "--camera-mode") {
                options.cameraGroupingExplicit = *supplied != "auto";
                if (*supplied == "single")
                    options.cameraGrouping =
                        aether::reconstruction::CameraGroupingMode::singleCamera;
                else if (*supplied == "per-folder")
                    options.cameraGrouping = aether::reconstruction::CameraGroupingMode::perFolder;
                else if (*supplied == "per-image")
                    options.cameraGrouping = aether::reconstruction::CameraGroupingMode::perImage;
                else if (*supplied != "auto") {
                    exitCode = fail("Camera mode must be auto, single, per-folder, or per-image",
                                    options.json);
                    return std::nullopt;
                }
            } else if (argument == "--trainer" && *supplied != "brush") {
                exitCode = fail("Only the pinned Brush adapter is supported", options.json);
                return std::nullopt;
            } else if (argument == "--seed" || argument == "--steps" ||
                       argument == "--checkpoint-every" || argument == "--sequential-overlap") {
                auto number = parsePositive(*supplied);
                if (!number) {
                    exitCode = fail("Seed/step value is invalid", options.json);
                    return std::nullopt;
                }
                if (argument == "--seed")
                    options.seed = *number;
                else if (argument == "--steps")
                    options.steps = *number;
                else if (argument == "--sequential-overlap")
                    options.sequentialOverlap = *number;
                else
                    options.checkpointEvery = *number;
            }
        } else if (!argument.empty() && argument.front() == '-') {
            exitCode = fail("Unknown option: " + std::string(argument), options.json);
            return std::nullopt;
        } else if (options.dataset.empty()) {
            options.dataset = argument;
        } else {
            exitCode = fail("Only one dataset may be specified", options.json);
            return std::nullopt;
        }
    }
    if (options.dataset.empty() || options.output.empty()) {
        exitCode = fail("Dataset and --output are required", options.json);
        return std::nullopt;
    }
    if (!options.matcherExplicit)
        options.matcher = aether::reconstruction::defaultMatcher(options.inputKind);
    if (!options.cameraGroupingExplicit)
        options.cameraGrouping = aether::reconstruction::defaultCameraGrouping(options.inputKind);
    if (options.sequentialOverlap > 1'000) {
        exitCode = fail("Sequential overlap must be between 1 and 1000", options.json);
        return std::nullopt;
    }
    if (options.cameraGrouping == aether::reconstruction::CameraGroupingMode::perFolder &&
        options.cameraGroups.empty()) {
        exitCode = fail("Per-folder camera grouping requires --camera-groups; camera identity "
                        "cannot be guessed",
                        options.json);
        return std::nullopt;
    }
    if (!options.cameraGroups.empty() &&
        options.cameraGrouping != aether::reconstruction::CameraGroupingMode::perFolder) {
        exitCode = fail("Camera-group manifests require --camera-mode per-folder", options.json);
        return std::nullopt;
    }
    return options;
}

std::string finalCheckpointName(std::uint32_t totalSteps) {
    const auto digits = std::to_string(totalSteps).size();
    std::ostringstream name;
    name << "checkpoint_" << std::setw(static_cast<int>(digits)) << std::setfill('0') << totalSteps
         << ".ply";
    return name.str();
}

std::optional<std::uint32_t> checkpointIteration(const std::filesystem::path& path,
                                                 std::uint32_t maximumIteration) {
    const std::string name = path.filename().string();
    constexpr std::string_view prefix = "checkpoint_";
    constexpr std::string_view suffix = ".ply";
    if (!name.starts_with(prefix) || !name.ends_with(suffix))
        return std::nullopt;
    const std::string_view digits(name.data() + prefix.size(),
                                  name.size() - prefix.size() - suffix.size());
    std::uint32_t iteration{};
    const auto parsed = std::from_chars(digits.data(), digits.data() + digits.size(), iteration);
    if (digits.empty() || parsed.ec != std::errc{} || parsed.ptr != digits.data() + digits.size() ||
        iteration == 0 || iteration > maximumIteration)
        return std::nullopt;
    return iteration;
}

aether::Result<std::optional<CheckpointRecovery>>
findLatestCheckpoint(const std::filesystem::path& directory, std::uint32_t maximumIteration) {
    std::error_code error;
    if (!std::filesystem::exists(directory, error))
        return std::optional<CheckpointRecovery>{};
    std::vector<std::pair<std::uint32_t, std::filesystem::path>> candidates;
    for (const auto& entry : std::filesystem::directory_iterator(directory, error)) {
        if (!entry.is_regular_file())
            continue;
        if (auto iteration = checkpointIteration(entry.path(), maximumIteration))
            candidates.emplace_back(*iteration, entry.path());
    }
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to enumerate Brush checkpoints",
                            error.message());
    std::ranges::sort(candidates, std::greater{}, &decltype(candidates)::value_type::first);
    std::size_t rejected = 0;
    for (const auto& [iteration, path] : candidates) {
        auto validated = aether::gaussian::PlyLoader::load(path);
        if (validated)
            return std::optional<CheckpointRecovery>{CheckpointRecovery{path, iteration, rejected}};
        ++rejected;
    }
    return std::optional<CheckpointRecovery>{};
}

aether::Result<void> atomicCopy(const std::filesystem::path& source,
                                const std::filesystem::path& destination) {
    const auto temporary = destination.string() + ".tmp";
    std::ifstream input(source, std::ios::binary);
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    std::array<char, 1ULL * 1024ULL * 1024ULL> buffer{};
    while (input) {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        if (input.gcount() > 0)
            output.write(buffer.data(), input.gcount());
    }
    output.close();
    if (!input.eof() || !output) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to copy Brush checkpoint",
                            source.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, destination, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize Brush checkpoint copy",
                            error.message());
    }
    return {};
}

aether::Result<void> ensureResumeKey(const std::filesystem::path& outputDirectory,
                                     std::string_view fingerprint) {
    const auto path = outputDirectory / "resume-key.txt";
    std::error_code error;
    if (std::filesystem::exists(path, error)) {
        std::ifstream stream(path);
        std::string existing;
        std::string extra;
        if (!std::getline(stream, existing) || existing.size() != 64 || std::getline(stream, extra))
            return aether::fail(aether::ErrorCode::corruptData,
                                "Reconstruction resume key is malformed", path.string());
        if (existing != fingerprint)
            return aether::fail(
                aether::ErrorCode::unsupported,
                "Reconstruction inputs or settings changed; choose a new job directory");
        return {};
    }
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to inspect reconstruction resume key",
                            error.message());
    if (std::filesystem::exists(outputDirectory / "job.json"))
        return aether::fail(aether::ErrorCode::unsupported,
                            "Existing reconstruction job predates safe resume fingerprints; choose "
                            "a new job directory");
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << fingerprint << '\n';
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to write reconstruction resume key",
                            path.string());
    }
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize reconstruction resume key",
                            error.message());
    }
    return {};
}

aether::Result<void> writeMarker(const std::filesystem::path& path) {
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << "complete\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to write stage marker", path.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize stage marker",
                            error.message());
    }
    return {};
}

aether::Result<InputImage> hashInputImage(const std::filesystem::path& path,
                                          const std::filesystem::path& root) {
    std::error_code error;
    const std::uintmax_t bytes = std::filesystem::file_size(path, error);
    if (error || bytes == 0)
        return aether::fail(aether::ErrorCode::io, "Unable to size reconstruction input",
                            path.string());
    std::ifstream stream(path, std::ios::binary);
    std::array<std::byte, 1ULL * 1024ULL * 1024ULL> buffer{};
    aether::package::Sha256 hash;
    while (stream) {
        stream.read(reinterpret_cast<char*>(buffer.data()),
                    static_cast<std::streamsize>(buffer.size()));
        const auto amount = static_cast<std::size_t>(stream.gcount());
        if (amount > 0)
            hash.update(std::span<const std::byte>(buffer.data(), amount));
    }
    if (!stream.eof())
        return aether::fail(aether::ErrorCode::io, "Unable to hash reconstruction input",
                            path.string());
    auto relative = std::filesystem::relative(path, root, error);
    if (error)
        relative = path.filename();
    return InputImage{relative, bytes, aether::package::Sha256::hex(hash.finalize())};
}

bool supportedImage(const std::filesystem::path& path) {
    std::string extension = path.extension().string();
    std::ranges::transform(extension, extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return extension == ".jpg" || extension == ".jpeg" || extension == ".png" ||
           extension == ".heic" || extension == ".tif" || extension == ".tiff";
}

aether::Result<std::filesystem::path> safeRelativeImage(std::string_view text) {
    std::filesystem::path path(text);
    if (path.empty() || path.is_absolute())
        return aether::fail(aether::ErrorCode::corruptData,
                            "Image-list entries must be relative paths", std::string(text));
    for (const auto& component : path)
        if (component == "..")
            return aether::fail(aether::ErrorCode::corruptData,
                                "Image-list path traversal is forbidden", std::string(text));
    path = path.lexically_normal();
    if (path == "." || !supportedImage(path))
        return aether::fail(aether::ErrorCode::corruptData,
                            "Image-list entry has an unsupported extension", std::string(text));
    return path;
}

aether::Result<std::vector<std::filesystem::path>>
discoverImagePaths(const Options& options, const std::filesystem::path& images) {
    constexpr std::size_t maximumImages = 1'000'000;
    std::vector<std::filesystem::path> paths;
    std::set<std::filesystem::path> unique;
    std::error_code filesystemError;
    if (!options.imageList.empty()) {
        std::ifstream stream(options.imageList);
        if (!stream)
            return aether::fail(aether::ErrorCode::notFound, "Unable to open image list",
                                options.imageList);
        std::string line;
        while (std::getline(stream, line)) {
            if (!line.empty() && line.back() == '\r')
                line.pop_back();
            if (line.empty() || line.front() == '#')
                continue;
            auto relative = safeRelativeImage(line);
            if (!relative)
                return std::unexpected(relative.error());
            if (!unique.insert(*relative).second)
                return aether::fail(aether::ErrorCode::corruptData,
                                    "Image-list entry is duplicated", *relative);
            const auto absolute = images / *relative;
            if (!std::filesystem::is_regular_file(absolute, filesystemError) || filesystemError)
                return aether::fail(aether::ErrorCode::notFound,
                                    "Image-list entry does not exist below the image root",
                                    *relative);
            paths.push_back(absolute);
            if (paths.size() > maximumImages)
                return aether::fail(aether::ErrorCode::resourceExhausted,
                                    "Image list exceeds the supported limit");
        }
        if (!stream.eof())
            return aether::fail(aether::ErrorCode::io, "Unable to read image list",
                                options.imageList);
    } else {
        std::filesystem::recursive_directory_iterator iterator(
            images, std::filesystem::directory_options::skip_permission_denied, filesystemError);
        const std::filesystem::recursive_directory_iterator end;
        while (!filesystemError && iterator != end) {
            std::error_code entryError;
            if (iterator->is_regular_file(entryError) && !entryError &&
                supportedImage(iterator->path()))
                paths.push_back(iterator->path());
            iterator.increment(filesystemError);
            if (paths.size() > maximumImages)
                return aether::fail(aether::ErrorCode::resourceExhausted,
                                    "Image directory exceeds the supported limit");
        }
        if (filesystemError)
            return aether::fail(aether::ErrorCode::io, "Unable to enumerate reconstruction images",
                                filesystemError.message());
        std::ranges::sort(paths);
    }
    if (paths.size() < 3)
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Dataset must contain at least three selected images");
    return paths;
}

void writeCoverageJson(std::ostream& stream,
                       const aether::reconstruction::SparseCoverageReport& coverage) {
    stream << "{\"passed\":" << (coverage.passed() ? "true" : "false")
           << ",\"inputImages\":" << coverage.inputImages
           << ",\"registeredImages\":" << coverage.registeredImages
           << ",\"registrationRatio\":" << coverage.registrationRatio
           << ",\"trackedPoints\":" << coverage.trackedPoints
           << ",\"meanTrackLength\":" << coverage.meanTrackLength
           << ",\"connectedImages\":" << coverage.connectedImages
           << ",\"connectedImageRatio\":" << coverage.connectedImageRatio
           << ",\"baselineDiagonal\":" << coverage.baselineDiagonal
           << ",\"maximumViewAngleDegrees\":" << coverage.maximumViewAngleDegrees
           << ",\"issues\":[";
    for (std::size_t index = 0; index < coverage.issues.size(); ++index) {
        if (index > 0)
            stream << ',';
        stream << '"' << escapeJson(coverage.issues[index]) << '"';
    }
    stream << "]}";
}

aether::Result<void>
writeCoverageReport(const std::filesystem::path& path,
                    const aether::reconstruction::SparseCoverageReport& coverage) {
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    writeCoverageJson(stream, coverage);
    stream << '\n';
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to write sparse coverage report",
                            path.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize sparse coverage report",
                            error.message());
    }
    return {};
}

aether::Result<void> writeSparseSelectionReport(const std::filesystem::path& path,
                                                const SparseSelectionEvidence& selection) {
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << "{\n  \"schemaVersion\":1,\n  \"selectedModel\":";
    if (selection.selectedIndex)
        stream << '"' << escapeJson(selection.candidates[*selection.selectedIndex].id) << '"';
    else
        stream << "null";
    stream << ",\n  \"reason\":\"" << escapeJson(selection.reason) << "\",\n  \"candidates\":[\n";
    for (std::size_t index = 0; index < selection.candidates.size(); ++index) {
        const auto& candidate = selection.candidates[index];
        stream << "    {\"id\":\"" << escapeJson(candidate.id) << "\",\"binaryDirectory\":\""
               << escapeJson(candidate.binaryDirectory.string()) << "\",\"textDirectory\":\""
               << escapeJson(candidate.textDirectory.string()) << "\",\"coverage\":";
        writeCoverageJson(stream, candidate.coverage);
        stream << '}' << (index + 1 == selection.candidates.size() ? "\n" : ",\n");
    }
    stream << "  ]\n}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to write sparse selection report", path);
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize sparse selection report",
                            error.message());
    }
    return {};
}

struct TextModelPublication final {
    std::filesystem::path source;
    std::filesystem::path destination;
};

aether::Result<void> publishSelectedTextModel(const TextModelPublication& publication) {
    const auto temporary = std::filesystem::path(publication.destination.string() + ".tmp");
    std::error_code error;
    std::filesystem::remove_all(temporary, error);
    error.clear();
    std::filesystem::create_directories(temporary, error);
    if (error)
        return aether::fail(aether::ErrorCode::io,
                            "Unable to create selected sparse model directory", error.message());
    constexpr std::array<std::string_view, 3> files{"cameras.txt", "images.txt", "points3D.txt"};
    for (const auto file : files) {
        const auto sourceFile = publication.source / file;
        if (!std::filesystem::is_regular_file(sourceFile)) {
            std::filesystem::remove_all(temporary);
            return aether::fail(aether::ErrorCode::notFound,
                                "Selected sparse text model is incomplete", sourceFile);
        }
        std::filesystem::copy_file(sourceFile, temporary / file,
                                   std::filesystem::copy_options::overwrite_existing, error);
        if (error) {
            std::filesystem::remove_all(temporary);
            return aether::fail(aether::ErrorCode::io, "Unable to copy selected sparse model",
                                error.message());
        }
    }
    std::filesystem::remove_all(publication.destination, error);
    if (error) {
        std::filesystem::remove_all(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to replace selected sparse model",
                            error.message());
    }
    std::filesystem::rename(temporary, publication.destination, error);
    if (error) {
        std::filesystem::remove_all(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to publish selected sparse model",
                            error.message());
    }
    return {};
}

aether::Result<void> writeManifest(const Options& options, const std::filesystem::path& images,
                                   const std::vector<InputImage>& inputImages,
                                   const std::vector<Stage>& stages, std::string_view status,
                                   const aether::reconstruction::SparseCoverageReport* coverage,
                                   const CheckpointRecovery* recovery, std::string_view resumeKey,
                                   const SparseSelectionEvidence* sparseSelection = nullptr,
                                   std::string_view failedStage = {}) {
    const auto path = options.output / "job.json";
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << "{\n  \"schemaVersion\":4,\n  \"status\":\"" << status << "\",\n  \"dataset\":\""
           << escapeJson(options.dataset.string()) << "\",\n  \"images\":\""
           << escapeJson(images.string()) << "\",\n  \"imageCount\":" << inputImages.size()
           << ",\n  \"seed\":" << options.seed << ",\n  \"steps\":" << options.steps
           << ",\n  \"checkpointEvery\":" << std::min(options.checkpointEvery, options.steps)
           << ",\n  \"resumeKey\":\"" << resumeKey << '"' << ",\n  \"inputKind\":\""
           << aether::reconstruction::toString(options.inputKind) << "\""
           << ",\n  \"matcher\":{\"strategy\":\""
           << aether::reconstruction::toString(options.matcher)
           << "\",\"sequentialOverlap\":" << options.sequentialOverlap << '}'
           << ",\n  \"cameraGrouping\":{\"mode\":\""
           << aether::reconstruction::toString(options.cameraGrouping) << "\",\"manifest\":\""
           << escapeJson(options.cameraGroups.string()) << "\",\"groups\":[";
    if (options.cameraGroupManifest)
        for (std::size_t index = 0; index < options.cameraGroupManifest->groups.size(); ++index) {
            const auto& group = options.cameraGroupManifest->groups[index];
            if (index > 0)
                stream << ',';
            stream << "{\"id\":\"" << escapeJson(group.id) << "\",\"relativeDirectory\":\""
                   << escapeJson(group.relativeDirectory.generic_string()) << "\",\"device\":\""
                   << escapeJson(group.device) << "\",\"lens\":\"" << escapeJson(group.lens)
                   << "\",\"calibrationId\":\"" << escapeJson(group.calibrationId) << '"';
            if (group.focalLengthMillimetres)
                stream << ",\"focalLengthMillimetres\":" << *group.focalLengthMillimetres;
            stream << '}';
        }
    stream << "]}"
           << ",\n  \"preprocessingManifest\":\""
           << escapeJson(options.preprocessingManifest.string()) << '"' << ",\n  \"imageList\":\""
           << escapeJson(options.imageList.string()) << '"'
           << ",\n  \"dependencies\":{\n    \"colmap\":{\"version\":\"3.13.0\","
              "\"commit\":\"0b31f98133b470eae62811b557dc2bcff1e4f9a5\"},\n"
              "    \"brush\":{\"version\":\"0.3.0\","
              "\"commit\":\"3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486\"},\n"
              "    \"proxy\":{\"version\":\"0.1.0\",\"open3d\":\"0.19.0\"}\n  },\n"
              "  \"inputs\":[\n";
    for (std::size_t index = 0; index < inputImages.size(); ++index) {
        stream << "    {\"path\":\"" << escapeJson(inputImages[index].path.string())
               << "\",\"bytes\":" << inputImages[index].bytes << ",\"sha256\":\""
               << inputImages[index].sha256 << "\"}"
               << (index + 1 == inputImages.size() ? "\n" : ",\n");
    }
    stream << "  ],\n  \"stages\":[\n";
    for (std::size_t index = 0; index < stages.size(); ++index) {
        stream << "    {\"name\":\"" << escapeJson(stages[index].name) << "\",\"command\":\""
               << escapeJson(commandDisplay(stages[index].arguments)) << "\",\"expectedOutput\":\""
               << escapeJson(stages[index].expectedOutput.string()) << '"';
        if (!stages[index].requiredCompanion.empty())
            stream << ",\"requiredCompanion\":\""
                   << escapeJson(stages[index].requiredCompanion.string()) << '"';
        stream << '}' << (index + 1 == stages.size() ? "\n" : ",\n");
    }
    stream << "  ]";
    if (coverage) {
        stream << ",\n  \"sparseCoverage\":";
        writeCoverageJson(stream, *coverage);
    }
    if (sparseSelection) {
        stream << ",\n  \"sparseSelection\":{\"selectedModel\":";
        if (sparseSelection->selectedIndex)
            stream << '"'
                   << escapeJson(sparseSelection->candidates[*sparseSelection->selectedIndex].id)
                   << '"';
        else
            stream << "null";
        stream << ",\"reason\":\"" << escapeJson(sparseSelection->reason) << "\"}";
    }
    if (!failedStage.empty())
        stream << ",\n  \"failedStage\":\"" << escapeJson(failedStage) << '"';
    if (recovery)
        stream << ",\n  \"checkpointRecovery\":{\"iteration\":" << recovery->iteration
               << ",\"source\":\"" << escapeJson(recovery->path.string())
               << "\",\"rejectedNewerCheckpoints\":" << recovery->rejectedNewerCheckpoints
               << ",\"optimizerStateRestored\":false}";
    stream << "\n}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to write reconstruction manifest",
                            path.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return aether::fail(aether::ErrorCode::io, "Unable to finalize reconstruction manifest",
                            error.message());
    }
    return {};
}

aether::Result<void> runStage(const Stage& stage, const std::filesystem::path& logPath) {
    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions) != 0)
        return aether::fail(aether::ErrorCode::internal, "Unable to initialize process actions");
    const int openResult = posix_spawn_file_actions_addopen(
        &actions, STDOUT_FILENO, logPath.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    const int duplicateResult =
        openResult == 0 ? posix_spawn_file_actions_adddup2(&actions, STDOUT_FILENO, STDERR_FILENO)
                        : openResult;
    if (duplicateResult != 0) {
        posix_spawn_file_actions_destroy(&actions);
        return aether::fail(aether::ErrorCode::io, "Unable to open reconstruction stage log",
                            logPath.string());
    }
    std::vector<char*> argv;
    argv.reserve(stage.arguments.size() + 1);
    for (const auto& argument : stage.arguments)
        argv.push_back(const_cast<char*>(argument.c_str()));
    argv.push_back(nullptr);
    pid_t child{};
    const int spawnResult =
        posix_spawnp(&child, argv.front(), &actions, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    if (spawnResult != 0)
        return aether::fail(aether::ErrorCode::notFound, "Unable to launch reconstruction tool",
                            stage.arguments.front());
    activeChild.store(child, std::memory_order_relaxed);
    int status{};
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
    }
    activeChild.store(-1, std::memory_order_relaxed);
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
        return aether::fail(aether::ErrorCode::io, "Reconstruction stage failed",
                            stage.name + " · log: " + logPath.string());
    return {};
}

bool stageComplete(const Stage& stage, const std::filesystem::path& outputDirectory) {
    const auto marker = outputDirectory / (stage.name + ".complete");
    return std::filesystem::is_regular_file(marker) &&
           std::filesystem::exists(stage.expectedOutput) &&
           (stage.requiredCompanion.empty() || std::filesystem::exists(stage.requiredCompanion));
}

aether::Result<void> executeStage(const Stage& stage,
                                  const std::filesystem::path& outputDirectory) {
    const bool complete = stageComplete(stage, outputDirectory);
    if (!complete) {
        if (auto result = runStage(stage, outputDirectory / "logs" / (stage.name + ".log"));
            !result)
            return std::unexpected(result.error());
    }
    if (!std::filesystem::exists(stage.expectedOutput))
        return aether::fail(aether::ErrorCode::notFound,
                            "Stage exited successfully but expected output is missing",
                            stage.expectedOutput);
    if (!stage.requiredCompanion.empty() && !std::filesystem::exists(stage.requiredCompanion))
        return aether::fail(aether::ErrorCode::notFound,
                            "Stage exited successfully but required companion output is missing",
                            stage.requiredCompanion);
    if (!complete)
        if (auto marker = writeMarker(outputDirectory / (stage.name + ".complete")); !marker)
            return std::unexpected(marker.error());
    return {};
}

aether::Result<std::vector<std::pair<std::uint32_t, std::filesystem::path>>>
enumerateSparseModels(const std::filesystem::path& sparseDirectory) {
    std::vector<std::pair<std::uint32_t, std::filesystem::path>> models;
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(sparseDirectory, error)) {
        if (!entry.is_directory())
            continue;
        const std::string name = entry.path().filename().string();
        std::uint32_t identifier{};
        const auto parsed = std::from_chars(name.data(), name.data() + name.size(), identifier);
        if (!name.empty() && parsed.ec == std::errc{} && parsed.ptr == name.data() + name.size())
            models.emplace_back(identifier, entry.path());
    }
    if (error)
        return aether::fail(aether::ErrorCode::io, "Unable to enumerate sparse COLMAP models",
                            error.message());
    std::ranges::sort(models, {}, &decltype(models)::value_type::first);
    if (models.empty())
        return aether::fail(aether::ErrorCode::notFound, "COLMAP mapper produced no sparse model",
                            sparseDirectory);
    return models;
}

aether::Result<void> verifyTool(const std::string& executable, std::string_view expectedVersion,
                                const std::filesystem::path& logPath) {
    std::vector<std::string> args = {executable};
    if (std::filesystem::path(executable).filename() != "colmap") {
        args.push_back("--version");
    }
    const Stage versionStage{"version-check", std::move(args), {}};
    if (auto result = runStage(versionStage, logPath); !result)
        return result;
    std::ifstream stream(logPath);
    const std::string output((std::istreambuf_iterator<char>(stream)),
                             std::istreambuf_iterator<char>());
    if (output.find(expectedVersion) == std::string::npos)
        return aether::fail(aether::ErrorCode::unsupported,
                            "Reconstruction tool version does not match the lock manifest",
                            executable + " expected " + std::string(expectedVersion));
    return {};
}
} // namespace

int run(int argc, char** argv) {
    int parseExitCode = 0;
    auto options = parseOptions(argc, argv, parseExitCode);
    if (!options)
        return parseExitCode;
    std::error_code filesystemError;
    if (!std::filesystem::is_directory(options->dataset, filesystemError))
        return fail("Dataset is not a directory: " + options->dataset.string(), options->json);
    std::filesystem::path images = options->dataset / "images";
    if (!std::filesystem::is_directory(images, filesystemError))
        images = options->dataset;
    auto discovered = discoverImagePaths(*options, images);
    if (!discovered)
        return fail(discovered.error().describe(), options->json);
    const auto& imagePaths = *discovered;
    std::vector<InputImage> inputImages;
    inputImages.reserve(imagePaths.size());
    for (const auto& path : imagePaths) {
        auto input = hashInputImage(path, images);
        if (!input)
            return fail(input.error().describe(), options->json);
        inputImages.push_back(std::move(*input));
    }
    if (!options->cameraGroups.empty()) {
        auto loaded = aether::reconstruction::loadCameraGroupManifest(options->cameraGroups);
        if (!loaded)
            return fail(loaded.error().describe(), options->json);
        std::vector<std::filesystem::path> relativeImages;
        relativeImages.reserve(inputImages.size());
        for (const auto& input : inputImages)
            relativeImages.push_back(input.path);
        if (auto validated = aether::reconstruction::validateCameraGroups(*loaded, relativeImages);
            !validated)
            return fail(validated.error().describe(), options->json);
        options->cameraGroupManifest = std::move(*loaded);
    }
    const std::size_t imageCount = inputImages.size();
    std::vector<std::filesystem::path> selectedImageNames;
    selectedImageNames.reserve(inputImages.size());
    for (const auto& input : inputImages)
        selectedImageNames.push_back(input.path);
    auto fingerprintResult = jobFingerprint(*options, inputImages);
    if (!fingerprintResult)
        return fail(fingerprintResult.error().describe(), options->json, 3);
    const std::string resumeKey = std::move(*fingerprintResult);

    const auto database = options->output / "database.db";
    const auto sparse = options->output / "sparse";
    const auto sparseModels = sparse / "models";
    const auto selectedText = sparse / "selected-text";
    const auto dense = options->output / "dense";
    const auto exports = options->output / "exports";
    const auto proxyDirectory = options->output / "proxy";
    const auto proxyMesh = proxyDirectory / "proxy.ply";
    const std::string seed = std::to_string(options->seed);
    const std::string steps = std::to_string(options->steps);
    const std::uint32_t checkpointInterval = std::min(options->checkpointEvery, options->steps);
    const auto finalCheckpoint = exports / finalCheckpointName(options->steps);
    auto checkpointResult = findLatestCheckpoint(exports, options->steps);
    if (!checkpointResult)
        return fail(checkpointResult.error().describe(), options->json, 3);
    std::optional<CheckpointRecovery> checkpointRecovery = std::move(*checkpointResult);
    std::vector<std::string> featureExtractionArgs{options->colmap,
                                                   "feature_extractor",
                                                   "--database_path",
                                                   database.string(),
                                                   "--image_path",
                                                   images.string(),
                                                   "--FeatureExtraction.use_gpu",
                                                   "0"};
    switch (options->cameraGrouping) {
    case aether::reconstruction::CameraGroupingMode::singleCamera:
        featureExtractionArgs.insert(featureExtractionArgs.end(),
                                     {"--ImageReader.single_camera", "1"});
        break;
    case aether::reconstruction::CameraGroupingMode::perFolder:
        featureExtractionArgs.insert(featureExtractionArgs.end(),
                                     {"--ImageReader.single_camera_per_folder", "1"});
        break;
    case aether::reconstruction::CameraGroupingMode::perImage:
        featureExtractionArgs.insert(featureExtractionArgs.end(),
                                     {"--ImageReader.single_camera_per_image", "1"});
        break;
    }
    if (!options->imageList.empty())
        featureExtractionArgs.insert(featureExtractionArgs.end(),
                                     {"--image_list_path", options->imageList.string()});

    std::vector<std::string> mapperArgs{options->colmap,        "mapper",
                                        "--database_path",      database.string(),
                                        "--image_path",         images.string(),
                                        "--output_path",        sparse.string(),
                                        "--Mapper.random_seed", seed,
                                        "--Mapper.ba_use_gpu",  "0"};
    if (!options->imageList.empty())
        mapperArgs.insert(mapperArgs.end(),
                          {"--Mapper.image_list_path", options->imageList.string()});

    if (options->testProfile == "synthetic-512") {
        featureExtractionArgs.push_back("--ImageReader.camera_model");
        featureExtractionArgs.push_back("PINHOLE");
        featureExtractionArgs.push_back("--ImageReader.camera_params");
        featureExtractionArgs.push_back("400,400,256,256");

        mapperArgs.push_back("--Mapper.init_min_num_inliers");
        mapperArgs.push_back("5");
        mapperArgs.push_back("--Mapper.init_min_tri_angle");
        mapperArgs.push_back("0.5");
        mapperArgs.push_back("--Mapper.abs_pose_min_num_inliers");
        mapperArgs.push_back("5");
        mapperArgs.push_back("--Mapper.min_num_matches");
        mapperArgs.push_back("5");
        mapperArgs.push_back("--Mapper.tri_min_angle");
        mapperArgs.push_back("0.5");
    }

    std::vector<std::string> matcherArguments{
        options->colmap,
        options->matcher == aether::reconstruction::MatcherStrategy::sequential
            ? "sequential_matcher"
            : "exhaustive_matcher",
        "--database_path",
        database.string(),
        "--FeatureMatching.use_gpu",
        "0",
        "--TwoViewGeometry.random_seed",
        seed};
    if (options->matcher == aether::reconstruction::MatcherStrategy::sequential)
        matcherArguments.insert(matcherArguments.end(),
                                {"--SequentialMatching.overlap",
                                 std::to_string(options->sequentialOverlap),
                                 "--SequentialMatching.loop_detection", "0"});

    std::vector<Stage> stages{
        {"feature-extraction", std::move(featureExtractionArgs), database},
        {"feature-matching", std::move(matcherArguments), database},
        {"sparse-mapping", std::move(mapperArgs), sparse},
    };

    if (options->dryRun) {
        if (options->json)
            std::cout << "{\"ok\":true,\"dryRun\":true,\"imageCount\":" << imageCount
                      << ",\"inputKind\":\"" << aether::reconstruction::toString(options->inputKind)
                      << "\",\"matcher\":\"" << aether::reconstruction::toString(options->matcher)
                      << "\",\"cameraGrouping\":\""
                      << aether::reconstruction::toString(options->cameraGrouping)
                      << "\",\"stages\":[";
        for (std::size_t index = 0; index < stages.size(); ++index) {
            if (options->json) {
                if (index > 0)
                    std::cout << ',';
                std::cout << "{\"name\":\"" << escapeJson(stages[index].name) << "\",\"command\":\""
                          << escapeJson(commandDisplay(stages[index].arguments)) << "\"}";
            } else {
                std::cout << stages[index].name << ": " << commandDisplay(stages[index].arguments)
                          << '\n';
            }
        }
        if (options->json) {
            if (!stages.empty())
                std::cout << ',';
            std::cout << "{\"name\":\"sparse-model-selection\",\"command\":\"internal: "
                         "enumerate, export, validate, and rank every COLMAP model\"}";
        } else {
            std::cout << "sparse-model-selection: internal: enumerate, export, validate, and rank "
                         "every COLMAP model\n";
        }
        if (options->json)
            std::cout << "]}\n";
        return 0;
    }

    std::filesystem::create_directories(options->output / "logs", filesystemError);
    std::filesystem::create_directories(sparse, filesystemError);
    std::filesystem::create_directories(sparseModels, filesystemError);
    std::filesystem::create_directories(dense, filesystemError);
    std::filesystem::create_directories(exports, filesystemError);
    std::filesystem::create_directories(proxyDirectory, filesystemError);
    if (filesystemError)
        return fail("Unable to create reconstruction job directories", options->json, 3);
    if (auto keyed = ensureResumeKey(options->output, resumeKey); !keyed)
        return fail(keyed.error().describe(), options->json, 3);
    if (auto manifest =
            writeManifest(*options, images, inputImages, stages, "running", nullptr,
                          checkpointRecovery ? &*checkpointRecovery : nullptr, resumeKey);
        !manifest)
        return fail(manifest.error().describe(), options->json, 3);
    const auto failJob = [&](std::string message, int code, std::string_view stage,
                             const aether::reconstruction::SparseCoverageReport* coverage = nullptr,
                             const SparseSelectionEvidence* selection = nullptr,
                             std::string_view status = "failed") {
        if (auto recorded = writeManifest(*options, images, inputImages, stages, status, coverage,
                                          checkpointRecovery ? &*checkpointRecovery : nullptr,
                                          resumeKey, selection, stage);
            !recorded)
            message +=
                " · additionally failed to persist job status: " + recorded.error().describe();
        return fail(message, options->json, code);
    };
    if (auto verified =
            verifyTool(options->colmap, "3.13.0", options->output / "logs" / "colmap-version.log");
        !verified) {
        return failJob(verified.error().describe(), 3, "colmap-version-check");
    }
    if (auto verified =
            verifyTool(options->brush, "0.3.0", options->output / "logs" / "brush-version.log");
        !verified) {
        return failJob(verified.error().describe(), 3, "brush-version-check");
    }
    if (auto verified = verifyTool(options->proxy, "aether-proxy 0.1.0",
                                   options->output / "logs" / "proxy-version.log");
        !verified) {
        return failJob(verified.error().describe(), 3, "proxy-version-check");
    }
    std::signal(SIGINT, interruptChild);
    std::signal(SIGTERM, interruptChild);
    for (const auto& stage : stages) {
        if (auto result = executeStage(stage, options->output); !result) {
            return failJob(result.error().describe(), 4, stage.name);
        }
    }

    auto models = enumerateSparseModels(sparse);
    if (!models) {
        std::filesystem::remove(options->output / "sparse-mapping.complete");
        return failJob(models.error().describe(), 4, "sparse-model-enumeration");
    }
    SparseSelectionEvidence sparseSelection;
    for (const auto& [identifier, binaryDirectory] : *models) {
        const std::string id = std::to_string(identifier);
        const auto textDirectory = sparseModels / (id + "-text");
        std::filesystem::create_directories(textDirectory, filesystemError);
        if (filesystemError)
            return failJob("Unable to create sparse model export directory", 4,
                           "sparse-model-export-" + id, nullptr, &sparseSelection);
        Stage exportStage{"sparse-model-export-" + id,
                          {options->colmap, "model_converter", "--input_path",
                           binaryDirectory.string(), "--output_path", textDirectory.string(),
                           "--output_type", "TXT"},
                          textDirectory / "images.txt",
                          textDirectory / "points3D.txt"};
        stages.push_back(exportStage);
        if (auto result = executeStage(exportStage, options->output); !result) {
            aether::reconstruction::SparseCoverageReport coverage;
            coverage.inputImages = imageCount;
            coverage.issues.push_back("Model export failed: " + result.error().describe());
            sparseSelection.candidates.push_back(
                {id, binaryDirectory, textDirectory, std::move(coverage)});
            continue;
        }
        auto coverage =
            aether::reconstruction::validateSparseTextModel(textDirectory, selectedImageNames);
        if (!coverage) {
            aether::reconstruction::SparseCoverageReport invalidCoverage;
            invalidCoverage.inputImages = imageCount;
            invalidCoverage.issues.push_back("Model validation failed: " +
                                             coverage.error().describe());
            sparseSelection.candidates.push_back(
                {id, binaryDirectory, textDirectory, std::move(invalidCoverage)});
            continue;
        }
        sparseSelection.candidates.push_back(
            {id, binaryDirectory, textDirectory, std::move(*coverage)});
    }
    auto selected = aether::reconstruction::selectBestSparseModel(sparseSelection.candidates);
    if (!selected) {
        sparseSelection.reason = selected.error().describe();
        std::string message = selected.error().describe();
        if (auto report = writeSparseSelectionReport(options->output / "sparse-selection.json",
                                                     sparseSelection);
            !report)
            message +=
                " · additionally failed to persist sparse selection: " + report.error().describe();
        return failJob(std::move(message), 5, "sparse-model-selection", nullptr, &sparseSelection,
                       "coverage-failed");
    }
    sparseSelection.selectedIndex = selected->candidateIndex;
    sparseSelection.reason = selected->reason;
    const auto& selectedCandidate = sparseSelection.candidates[*sparseSelection.selectedIndex];
    const auto& sparseCoverage = selectedCandidate.coverage;
    if (auto report =
            writeSparseSelectionReport(options->output / "sparse-selection.json", sparseSelection);
        !report)
        return failJob(report.error().describe(), 4, "sparse-selection-report", &sparseCoverage,
                       &sparseSelection);
    if (auto published = publishSelectedTextModel(
            TextModelPublication{selectedCandidate.textDirectory, selectedText});
        !published)
        return failJob(published.error().describe(), 4, "selected-model-publication",
                       &sparseCoverage, &sparseSelection);
    if (auto report = writeCoverageReport(options->output / "pose-coverage.json", sparseCoverage);
        !report)
        return failJob(report.error().describe(), 4, "pose-coverage-report", &sparseCoverage,
                       &sparseSelection);
    if (auto marker = writeMarker(options->output / "pose-coverage-validation.complete"); !marker)
        return failJob(marker.error().describe(), 4, "pose-coverage-marker", &sparseCoverage,
                       &sparseSelection);

    std::vector<std::string> proxyArguments{
        options->proxy, (selectedText / "points3D.txt").string(), "--output", proxyMesh.string(),
        "--report",     (proxyDirectory / "proxy.json").string(), "--json"};
    if (!options->proxyConfig.empty())
        proxyArguments.insert(proxyArguments.end(), {"--config", options->proxyConfig.string()});
    std::vector<std::string> brushArguments{options->brush,   dense.string(),
                                            "--seed",         seed,
                                            "--total-steps",  steps,
                                            "--export-every", std::to_string(checkpointInterval),
                                            "--export-path",  exports.string(),
                                            "--export-name",  "checkpoint_{iter}.ply"};
    if (checkpointRecovery)
        brushArguments.insert(brushArguments.end(),
                              {"--start-iter", std::to_string(checkpointRecovery->iteration)});
    std::vector<Stage> postStages{
        {"proxy-generation", std::move(proxyArguments), proxyMesh, proxyDirectory / "proxy.json"},
        {"undistortion",
         {options->colmap, "image_undistorter", "--image_path", images.string(), "--input_path",
          selectedCandidate.binaryDirectory.string(), "--output_path", dense.string(),
          "--output_type", "COLMAP"},
         dense / "sparse"},
        {"brush-training", std::move(brushArguments), finalCheckpoint},
    };
    stages.insert(stages.end(), postStages.begin(), postStages.end());
    if (auto manifest = writeManifest(
            *options, images, inputImages, stages, "running", &sparseCoverage,
            checkpointRecovery ? &*checkpointRecovery : nullptr, resumeKey, &sparseSelection);
        !manifest)
        return fail(manifest.error().describe(), options->json, 4);
    for (const auto& stage : postStages) {
        if (stage.name == "brush-training" && checkpointRecovery &&
            !stageComplete(stage, options->output)) {
            if (auto restored = atomicCopy(checkpointRecovery->path, dense / "init.ply"); !restored)
                return failJob(restored.error().describe(), 4, "checkpoint-recovery",
                               &sparseCoverage, &sparseSelection);
        }
        if (auto result = executeStage(stage, options->output); !result) {
            return failJob(result.error().describe(), 4, stage.name, &sparseCoverage,
                           &sparseSelection);
        }
    }
    if (auto validated = aether::gaussian::PlyLoader::load(finalCheckpoint); !validated)
        return failJob("Brush final checkpoint failed strict 3DGS validation: " +
                           validated.error().describe(),
                       4, "final-checkpoint-validation", &sparseCoverage, &sparseSelection);
    if (auto copied = atomicCopy(finalCheckpoint, exports / "base-gaussians.ply"); !copied)
        return failJob(copied.error().describe(), 4, "base-gaussian-publication", &sparseCoverage,
                       &sparseSelection);
    if (auto manifest = writeManifest(
            *options, images, inputImages, stages, "complete", &sparseCoverage,
            checkpointRecovery ? &*checkpointRecovery : nullptr, resumeKey, &sparseSelection);
        !manifest)
        return fail(manifest.error().describe(), options->json, 4);
    if (options->json)
        std::cout << "{\"ok\":true,\"output\":\""
                  << escapeJson((exports / "base-gaussians.ply").string())
                  << "\",\"images\":" << imageCount << ",\"proxy\":\""
                  << escapeJson(proxyMesh.string()) << "\""
                  << ",\"selectedModel\":\"" << escapeJson(selectedCandidate.id) << "\""
                  << ",\"matcher\":\"" << aether::reconstruction::toString(options->matcher) << "\""
                  << ",\"cameraGrouping\":\""
                  << aether::reconstruction::toString(options->cameraGrouping) << "\""
                  << ",\"registeredImages\":" << sparseCoverage.registeredImages
                  << ",\"trackedPoints\":" << sparseCoverage.trackedPoints
                  << ",\"seed\":" << options->seed << "}\n";
    else
        std::cout << "Reconstruction complete: " << exports / "base-gaussians.ply" << '\n';
    return 0;
}

int main(int argc, char** argv) noexcept {
    try {
        return run(argc, argv);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Unhandled reconstruction failure: %s\n", error.what());
    } catch (...) {
        std::fputs("Unhandled reconstruction failure\n", stderr);
    }
    return 5;
}
