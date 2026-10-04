#include <aether/reconstruction/ReconstructionInput.hpp>

#include <simdjson.h>

#include <array>
#include <cmath>
#include <fstream>
#include <limits>
#include <set>
#include <string_view>

namespace aether::reconstruction {
namespace {
constexpr std::size_t maximumManifestBytes = 1ULL * 1024ULL * 1024ULL;
constexpr std::size_t maximumGroups = 128;
constexpr std::size_t maximumStringBytes = 1024;

Result<std::string> requiredString(simdjson::dom::element object, const char* field) {
    std::string_view value;
    if (object[field].get(value) || value.empty() || value.size() > maximumStringBytes)
        return fail(ErrorCode::corruptData, "Camera-group string field is invalid", field);
    return std::string(value);
}

Result<std::string> optionalString(simdjson::dom::element object, const char* field) {
    const auto candidate = object[field];
    if (candidate.error() == simdjson::NO_SUCH_FIELD)
        return std::string{};
    std::string_view value;
    if (candidate.get(value) || value.size() > maximumStringBytes)
        return fail(ErrorCode::corruptData, "Camera-group string field is invalid", field);
    return std::string(value);
}

Result<std::filesystem::path> relativeDirectory(simdjson::dom::element object) {
    auto text = requiredString(object, "relativeDirectory");
    if (!text)
        return std::unexpected(text.error());
    std::filesystem::path path(*text);
    if (path.empty() || path.is_absolute())
        return fail(ErrorCode::corruptData, "Camera-group directory must be relative");
    for (const auto& component : path)
        if (component == "..")
            return fail(ErrorCode::corruptData, "Camera-group path traversal is forbidden");
    path = path.lexically_normal();
    if (path == "." || std::distance(path.begin(), path.end()) != 1)
        return fail(ErrorCode::corruptData,
                    "Camera-group directory must name one direct child folder");
    return path;
}
} // namespace

Result<CameraGroupManifest> loadCameraGroupManifest(const std::filesystem::path& path) {
    std::error_code filesystemError;
    const auto bytes = std::filesystem::file_size(path, filesystemError);
    if (filesystemError || bytes == 0 || bytes > maximumManifestBytes)
        return fail(ErrorCode::corruptData, "Camera-group manifest size is invalid", path);
    std::array<char, maximumManifestBytes + simdjson::SIMDJSON_PADDING> storage{};
    std::ifstream stream(path, std::ios::binary);
    stream.read(storage.data(), static_cast<std::streamsize>(bytes));
    if (stream.gcount() != static_cast<std::streamsize>(bytes) || !stream)
        return fail(ErrorCode::io, "Unable to read camera-group manifest", path);
    simdjson::dom::parser parser(maximumManifestBytes);
    auto documentResult = parser.parse(storage.data(), static_cast<std::size_t>(bytes), false);
    if (documentResult.error())
        return fail(ErrorCode::corruptData, "Camera-group manifest is not valid JSON", path);
    simdjson::dom::element document = documentResult.value();
    std::uint64_t schemaVersion{};
    if (document["schemaVersion"].get(schemaVersion) || schemaVersion != 1)
        return fail(ErrorCode::unsupported, "Camera-group schema version is unsupported", path);
    simdjson::dom::array groups;
    if (document["groups"].get_array().get(groups) || groups.size() == 0 ||
        groups.size() > maximumGroups)
        return fail(ErrorCode::corruptData, "Camera-group array is empty or exceeds its limit",
                    path);
    CameraGroupManifest manifest;
    std::set<std::string> identifiers;
    std::set<std::filesystem::path> directories;
    for (auto element : groups) {
        CameraGroup group;
        auto id = requiredString(element, "id");
        auto directory = relativeDirectory(element);
        auto device = requiredString(element, "device");
        auto lens = requiredString(element, "lens");
        auto calibration = optionalString(element, "calibrationId");
        if (!id)
            return std::unexpected(id.error());
        if (!directory)
            return std::unexpected(directory.error());
        if (!device)
            return std::unexpected(device.error());
        if (!lens)
            return std::unexpected(lens.error());
        if (!calibration)
            return std::unexpected(calibration.error());
        group.id = std::move(*id);
        group.relativeDirectory = std::move(*directory);
        group.device = std::move(*device);
        group.lens = std::move(*lens);
        group.calibrationId = std::move(*calibration);
        const auto focalField = element["focalLengthMillimetres"];
        if (focalField.error() != simdjson::NO_SUCH_FIELD) {
            double focalLength{};
            if (focalField.get(focalLength) || !std::isfinite(focalLength) || focalLength <= 0.0 ||
                focalLength > 2'000.0)
                return fail(ErrorCode::corruptData,
                            "Camera-group focal length is outside the supported range", group.id);
            group.focalLengthMillimetres = focalLength;
        }
        if (!identifiers.insert(group.id).second)
            return fail(ErrorCode::corruptData, "Camera-group ID is duplicated", group.id);
        if (!directories.insert(group.relativeDirectory).second)
            return fail(ErrorCode::corruptData, "Camera-group directory is duplicated",
                        group.relativeDirectory);
        manifest.groups.push_back(std::move(group));
    }
    return manifest;
}

Result<void> validateCameraGroups(const CameraGroupManifest& manifest,
                                  const std::vector<std::filesystem::path>& relativeImages) {
    if (manifest.schemaVersion != 1 || manifest.groups.empty() || relativeImages.empty())
        return fail(ErrorCode::invalidArgument, "Camera-group validation input is empty");
    std::vector<std::size_t> membership(manifest.groups.size());
    for (const auto& image : relativeImages) {
        if (image.empty() || image.is_absolute())
            return fail(ErrorCode::invalidArgument, "Camera-group image path must be relative",
                        image);
        std::optional<std::size_t> matched;
        for (std::size_t index = 0; index < manifest.groups.size(); ++index)
            if (image.parent_path().lexically_normal() ==
                manifest.groups[index].relativeDirectory.lexically_normal()) {
                if (matched)
                    return fail(ErrorCode::corruptData,
                                "Image belongs to more than one camera group", image);
                matched = index;
            }
        if (!matched)
            return fail(ErrorCode::corruptData, "Image is not covered by a camera group", image);
        ++membership[*matched];
    }
    for (std::size_t index = 0; index < membership.size(); ++index)
        if (membership[index] == 0)
            return fail(ErrorCode::corruptData, "Camera group contains no selected images",
                        manifest.groups[index].id);
    return {};
}

MatcherStrategy defaultMatcher(ReconstructionInputKind kind) noexcept {
    return kind == ReconstructionInputKind::video ? MatcherStrategy::sequential
                                                  : MatcherStrategy::exhaustive;
}

CameraGroupingMode defaultCameraGrouping(ReconstructionInputKind kind) noexcept {
    return kind == ReconstructionInputKind::multiCamera ? CameraGroupingMode::perFolder
                                                        : CameraGroupingMode::singleCamera;
}

std::string_view toString(ReconstructionInputKind kind) noexcept {
    switch (kind) {
    case ReconstructionInputKind::unorderedPhotos:
        return "photos";
    case ReconstructionInputKind::video:
        return "video";
    case ReconstructionInputKind::multiCamera:
        return "multi-camera";
    }
    return "unknown";
}

std::string_view toString(MatcherStrategy strategy) noexcept {
    return strategy == MatcherStrategy::exhaustive ? "exhaustive" : "sequential";
}

std::string_view toString(CameraGroupingMode mode) noexcept {
    switch (mode) {
    case CameraGroupingMode::singleCamera:
        return "single";
    case CameraGroupingMode::perFolder:
        return "per-folder";
    case CameraGroupingMode::perImage:
        return "per-image";
    }
    return "unknown";
}

} // namespace aether::reconstruction
