#include <aether/canonical/CanonicalAsset.hpp>

#include <aether/mesh/GltfLoader.hpp>

#include <simdjson.h>

#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <set>
#include <string_view>

namespace aether::canonical {
namespace {

constexpr std::array<std::byte, 8> cameraMagic{std::byte{'A'}, std::byte{'E'}, std::byte{'T'},
                                               std::byte{'H'}, std::byte{'C'}, std::byte{'A'},
                                               std::byte{'M'}, std::byte{0}};
constexpr std::array<std::byte, 8> confidenceMagic{std::byte{'A'}, std::byte{'E'}, std::byte{'T'},
                                                   std::byte{'H'}, std::byte{'C'}, std::byte{'F'},
                                                   std::byte{0},   std::byte{0}};
constexpr std::uint64_t missingTimestamp = std::numeric_limits<std::uint64_t>::max();
constexpr std::size_t maximumStringBytes = 256ULL * 1024ULL * 1024ULL;
constexpr std::size_t maximumGlbJsonBytes = 256ULL * 1024ULL * 1024ULL;

void append16(std::vector<std::byte>& output, std::uint16_t value) {
    output.push_back(static_cast<std::byte>(value & 0xffU));
    output.push_back(static_cast<std::byte>((value >> 8U) & 0xffU));
}

void append32(std::vector<std::byte>& output, std::uint32_t value) {
    for (std::uint32_t shift = 0; shift < 32; shift += 8)
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
}

void append64(std::vector<std::byte>& output, std::uint64_t value) {
    for (std::uint32_t shift = 0; shift < 64; shift += 8)
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
}

void appendDouble(std::vector<std::byte>& output, double value) {
    append64(output, std::bit_cast<std::uint64_t>(value));
}

void appendFloat(std::vector<std::byte>& output, float value) {
    append32(output, std::bit_cast<std::uint32_t>(value));
}

std::uint16_t read16(const std::byte* bytes) {
    return static_cast<std::uint16_t>(std::to_integer<std::uint16_t>(bytes[0]) |
                                      (std::to_integer<std::uint16_t>(bytes[1]) << 8U));
}

std::uint32_t read32(const std::byte* bytes) {
    std::uint32_t result{};
    for (std::uint32_t index = 0; index < 4; ++index)
        result |= std::to_integer<std::uint32_t>(bytes[index]) << (index * 8U);
    return result;
}

std::uint64_t read64(const std::byte* bytes) {
    std::uint64_t result{};
    for (std::uint32_t index = 0; index < 8; ++index)
        result |= std::to_integer<std::uint64_t>(bytes[index]) << (index * 8U);
    return result;
}

double readDouble(const std::byte* bytes) {
    return std::bit_cast<double>(read64(bytes));
}

float readFloat(const std::byte* bytes) {
    return std::bit_cast<float>(read32(bytes));
}

Result<std::vector<std::byte>> readFile(const std::filesystem::path& path,
                                        std::uintmax_t maximumBytes) {
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    if (error || size == 0)
        return fail(ErrorCode::notFound, "Canonical asset input is missing or empty", path);
    if (size > maximumBytes || size > std::numeric_limits<std::size_t>::max())
        return fail(ErrorCode::resourceExhausted, "Canonical asset input exceeds its byte limit",
                    path);
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    std::ifstream stream(path, std::ios::binary);
    stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!stream)
        return fail(ErrorCode::io, "Unable to read canonical asset input", path);
    return bytes;
}

Result<std::filesystem::path> containedFile(const std::filesystem::path& root,
                                            const std::filesystem::path& relative) {
    std::error_code error;
    const auto canonicalRoot = std::filesystem::weakly_canonical(root, error);
    if (error)
        return fail(ErrorCode::io, "Unable to resolve canonical asset root", error.message());
    auto candidate = std::filesystem::weakly_canonical(root / relative, error);
    if (error)
        return fail(ErrorCode::notFound, "Unable to resolve canonical asset input", relative);
    auto rootIterator = canonicalRoot.begin();
    auto candidateIterator = candidate.begin();
    for (; rootIterator != canonicalRoot.end() && candidateIterator != candidate.end();
         ++rootIterator, ++candidateIterator)
        if (*rootIterator != *candidateIterator)
            return fail(ErrorCode::corruptData, "Canonical asset symlink escapes its root",
                        relative);
    if (rootIterator != canonicalRoot.end())
        return fail(ErrorCode::corruptData, "Canonical asset input is outside its root", relative);
    return candidate;
}

bool validSha256(std::string_view value) {
    return value.size() == 64 &&
           std::ranges::all_of(
               value, [](unsigned char character) { return std::isxdigit(character) != 0; }) &&
           std::ranges::any_of(value, [](char character) { return character != '0'; });
}

Result<std::filesystem::path> relativeFile(simdjson::dom::element object, const char* field,
                                           std::string_view requiredExtension = {}) {
    std::string_view text;
    if (object[field].get_string().get(text) || text.empty() || text.size() > 4096)
        return fail(ErrorCode::corruptData, "Canonical asset path is missing or invalid", field);
    std::filesystem::path path(text);
    if (path.is_absolute())
        return fail(ErrorCode::corruptData, "Canonical asset paths must be relative", field);
    for (const auto& component : path)
        if (component == "..")
            return fail(ErrorCode::corruptData, "Canonical asset path traversal is forbidden",
                        field);
    path = path.lexically_normal();
    if (path.empty() || path == "." ||
        (!requiredExtension.empty() && path.extension() != requiredExtension))
        return fail(ErrorCode::corruptData, "Canonical asset path has an invalid extension", field);
    return path;
}

Result<std::string> requiredString(simdjson::dom::element object, const char* field,
                                   std::size_t maximumBytes = 1024) {
    std::string_view value;
    if (object[field].get_string().get(value) || value.empty() || value.size() > maximumBytes)
        return fail(ErrorCode::corruptData, "Canonical asset string is missing or invalid", field);
    return std::string(value);
}

Result<ProviderProvenance> provider(simdjson::dom::element object, const char* field) {
    simdjson::dom::object source;
    if (object[field].get_object().get(source))
        return fail(ErrorCode::corruptData, "Canonical provider provenance is missing", field);
    auto name = requiredString(source, "name");
    auto version = requiredString(source, "version");
    auto inputHash = requiredString(source, "inputSha256", 64);
    auto configurationHash = requiredString(source, "configurationSha256", 64);
    if (!name)
        return std::unexpected(name.error());
    if (!version)
        return std::unexpected(version.error());
    if (!inputHash || !validSha256(*inputHash))
        return fail(ErrorCode::corruptData, "Provider input SHA-256 is invalid", field);
    if (!configurationHash || !validSha256(*configurationHash))
        return fail(ErrorCode::corruptData, "Provider configuration SHA-256 is invalid", field);
    return ProviderProvenance{std::move(*name), std::move(*version), std::move(*inputHash),
                              std::move(*configurationHash)};
}

Result<CanonicalManifest> parseManifestBytes(std::span<const std::byte> bytes) {
    if (bytes.empty() || bytes.size() > 1ULL * 1024ULL * 1024ULL)
        return fail(ErrorCode::resourceExhausted, "Canonical asset manifest size is invalid");
    simdjson::dom::parser parser;
    simdjson::padded_string json(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    auto parsed = parser.parse(json);
    if (parsed.error())
        return fail(ErrorCode::corruptData, "Unable to parse canonical asset manifest",
                    simdjson::error_message(parsed.error()));
    simdjson::dom::element document = parsed.value();
    std::uint64_t schemaVersion{};
    if (document["schemaVersion"].get(schemaVersion) || schemaVersion != 1)
        return fail(ErrorCode::unsupported, "Canonical asset schema version is unsupported");
    auto name = requiredString(document, "name");
    auto coordinateSystem = requiredString(document, "coordinateSystem");
    double metersPerUnit{};
    if (!name)
        return std::unexpected(name.error());
    if (!coordinateSystem)
        return std::unexpected(coordinateSystem.error());
    if (*coordinateSystem != "right-handed-y-up-negative-z-forward")
        return fail(ErrorCode::unsupported, "Canonical asset coordinate system is unsupported",
                    *coordinateSystem);
    if (document["metersPerUnit"].get(metersPerUnit) || !std::isfinite(metersPerUnit) ||
        std::abs(metersPerUnit - 1.0) > 1.0e-12)
        return fail(ErrorCode::unsupported, "Canonical Asset v1 requires metre geometry");
    auto mesh = relativeFile(document, "mesh", ".glb");
    auto cameras = relativeFile(document, "cameras", ".json");
    auto geometryProvider = provider(document, "geometryProvider");
    auto appearanceProvider = provider(document, "appearanceProvider");
    if (!mesh)
        return std::unexpected(mesh.error());
    if (!cameras)
        return std::unexpected(cameras.error());
    if (!geometryProvider)
        return std::unexpected(geometryProvider.error());
    if (!appearanceProvider)
        return std::unexpected(appearanceProvider.error());

    simdjson::dom::object confidenceObject;
    if (document["confidence"].get_object().get(confidenceObject))
        return fail(ErrorCode::corruptData, "Canonical confidence declaration is missing");
    auto confidenceKind = requiredString(confidenceObject, "kind");
    if (!confidenceKind)
        return std::unexpected(confidenceKind.error());

    CanonicalManifest manifest;
    manifest.name = std::move(*name);
    manifest.coordinateSystem = std::move(*coordinateSystem);
    manifest.metersPerUnit = metersPerUnit;
    manifest.mesh = std::move(*mesh);
    manifest.cameras = std::move(*cameras);
    manifest.geometryProvider = std::move(*geometryProvider);
    manifest.appearanceProvider = std::move(*appearanceProvider);
    if (*confidenceKind == "uniform") {
        double value{};
        if (confidenceObject["value"].get(value) || !std::isfinite(value) || value < 0.0 ||
            value > 1.0)
            return fail(ErrorCode::corruptData, "Uniform canonical confidence is invalid");
        manifest.confidenceSource = ConfidenceSource::uniform;
        manifest.uniformConfidence = static_cast<float>(value);
    } else if (*confidenceKind == "per-vertex") {
        auto path = relativeFile(confidenceObject, "file", ".bin");
        if (!path)
            return std::unexpected(path.error());
        manifest.confidenceSource = ConfidenceSource::perVertex;
        manifest.confidence = std::move(*path);
    } else {
        return fail(ErrorCode::unsupported, "Canonical confidence kind is unsupported",
                    *confidenceKind);
    }
    return manifest;
}

Result<void> validateCamera(const CameraRecord& camera) {
    if (camera.id.empty() || camera.sourceId.empty() || camera.id.size() > 4096 ||
        camera.sourceId.size() > 4096)
        return fail(ErrorCode::corruptData, "Canonical camera identity is invalid");
    if (camera.image.empty() || camera.image.is_absolute() ||
        camera.image.generic_string().size() > 4096)
        return fail(ErrorCode::corruptData, "Canonical camera image path is invalid", camera.id);
    for (const auto& component : camera.image)
        if (component == "..")
            return fail(ErrorCode::corruptData,
                        "Canonical camera image path traversal is forbidden", camera.id);
    if (camera.width == 0 || camera.height == 0 || camera.width > 100'000 ||
        camera.height > 100'000)
        return fail(ErrorCode::corruptData, "Canonical camera dimensions are invalid", camera.id);
    const auto [fx, fy, cx, cy] = camera.intrinsics;
    if (!std::isfinite(fx) || !std::isfinite(fy) || !std::isfinite(cx) || !std::isfinite(cy) ||
        fx <= 0.0 || fy <= 0.0 || cx < -static_cast<double>(camera.width) ||
        cx > 2.0 * static_cast<double>(camera.width) || cy < -static_cast<double>(camera.height) ||
        cy > 2.0 * static_cast<double>(camera.height))
        return fail(ErrorCode::corruptData, "Canonical camera intrinsics are invalid", camera.id);
    if (!std::ranges::all_of(camera.cameraToWorld,
                             [](double value) { return std::isfinite(value); }))
        return fail(ErrorCode::corruptData, "Canonical camera transform is not finite", camera.id);
    constexpr double tolerance = 1.0e-4;
    if (std::abs(camera.cameraToWorld[3]) > tolerance ||
        std::abs(camera.cameraToWorld[7]) > tolerance ||
        std::abs(camera.cameraToWorld[11]) > tolerance ||
        std::abs(camera.cameraToWorld[15] - 1.0) > tolerance)
        return fail(ErrorCode::corruptData, "Canonical camera transform is not affine", camera.id);
    const std::array<std::array<double, 3>, 3> axes{{
        {camera.cameraToWorld[0], camera.cameraToWorld[1], camera.cameraToWorld[2]},
        {camera.cameraToWorld[4], camera.cameraToWorld[5], camera.cameraToWorld[6]},
        {camera.cameraToWorld[8], camera.cameraToWorld[9], camera.cameraToWorld[10]},
    }};
    const auto dot = [](const auto& left, const auto& right) {
        return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
    };
    for (const auto& axis : axes)
        if (std::abs(dot(axis, axis) - 1.0) > 1.0e-3)
            return fail(ErrorCode::corruptData, "Canonical camera rotation is not normalized",
                        camera.id);
    if (std::abs(dot(axes[0], axes[1])) > 1.0e-3 || std::abs(dot(axes[0], axes[2])) > 1.0e-3 ||
        std::abs(dot(axes[1], axes[2])) > 1.0e-3)
        return fail(ErrorCode::corruptData, "Canonical camera rotation is not orthogonal",
                    camera.id);
    const double determinant = axes[0][0] * (axes[1][1] * axes[2][2] - axes[1][2] * axes[2][1]) -
                               axes[1][0] * (axes[0][1] * axes[2][2] - axes[0][2] * axes[2][1]) +
                               axes[2][0] * (axes[0][1] * axes[1][2] - axes[0][2] * axes[1][1]);
    if (std::abs(determinant - 1.0) > 1.0e-3)
        return fail(ErrorCode::corruptData, "Canonical camera rotation changes handedness",
                    camera.id);
    if (!std::isfinite(camera.confidence) || camera.confidence < 0.0 || camera.confidence > 1.0)
        return fail(ErrorCode::corruptData, "Canonical camera confidence is invalid", camera.id);
    return {};
}

Result<void> validateRig(const CameraRig& rig, std::size_t maximumCameras) {
    if (rig.cameras.empty() || rig.cameras.size() > maximumCameras)
        return fail(ErrorCode::resourceExhausted, "Canonical camera count is invalid");
    std::set<std::string> ids;
    std::set<std::filesystem::path> images;
    for (const auto& camera : rig.cameras) {
        if (auto validated = validateCamera(camera); !validated)
            return validated;
        if (!ids.insert(camera.id).second)
            return fail(ErrorCode::corruptData, "Canonical camera ID is duplicated", camera.id);
        if (!images.insert(camera.image.lexically_normal()).second)
            return fail(ErrorCode::corruptData, "Canonical camera image is duplicated",
                        camera.image);
    }
    return {};
}

Result<std::vector<double>> numberArray(simdjson::dom::element object, const char* field,
                                        std::size_t count) {
    simdjson::dom::array array;
    if (object[field].get_array().get(array) || array.size() != count)
        return fail(ErrorCode::corruptData, "Canonical camera array size is invalid", field);
    std::vector<double> result;
    result.reserve(count);
    for (const auto element : array) {
        double value{};
        if (element.get(value) || !std::isfinite(value))
            return fail(ErrorCode::corruptData, "Canonical camera array contains invalid data",
                        field);
        result.push_back(value);
    }
    return result;
}

Result<CameraRig> loadCameraJson(const std::filesystem::path& path,
                                 const CanonicalAssetLimits& limits) {
    auto bytes = readFile(path, limits.maximumCameraJsonBytes);
    if (!bytes)
        return std::unexpected(bytes.error());
    simdjson::dom::parser parser;
    simdjson::padded_string json(reinterpret_cast<const char*>(bytes->data()), bytes->size());
    auto parsed = parser.parse(json);
    if (parsed.error())
        return fail(ErrorCode::corruptData, "Unable to parse canonical camera JSON",
                    simdjson::error_message(parsed.error()));
    simdjson::dom::element document = parsed.value();
    std::uint64_t schemaVersion{};
    if (document["schemaVersion"].get(schemaVersion) || schemaVersion != 1)
        return fail(ErrorCode::unsupported, "Canonical camera schema version is unsupported");
    simdjson::dom::array cameras;
    if (document["cameras"].get_array().get(cameras) || cameras.size() == 0 ||
        cameras.size() > limits.maximumCameras)
        return fail(ErrorCode::resourceExhausted, "Canonical camera JSON count is invalid");
    CameraRig rig;
    rig.cameras.reserve(cameras.size());
    for (const auto element : cameras) {
        auto id = requiredString(element, "id", 4096);
        auto sourceId = requiredString(element, "sourceId", 4096);
        auto image = relativeFile(element, "image");
        auto intrinsics = numberArray(element, "intrinsics", 4);
        auto transform = numberArray(element, "cameraToWorld", 16);
        std::uint64_t width{};
        std::uint64_t height{};
        double confidence{};
        if (!id)
            return std::unexpected(id.error());
        if (!sourceId)
            return std::unexpected(sourceId.error());
        if (!image)
            return std::unexpected(image.error());
        if (!intrinsics)
            return std::unexpected(intrinsics.error());
        if (!transform)
            return std::unexpected(transform.error());
        if (element["width"].get(width) || element["height"].get(height) ||
            width > std::numeric_limits<std::uint32_t>::max() ||
            height > std::numeric_limits<std::uint32_t>::max() ||
            element["confidence"].get(confidence))
            return fail(ErrorCode::corruptData, "Canonical camera scalar is invalid", *id);
        CameraRecord camera;
        camera.id = std::move(*id);
        camera.sourceId = std::move(*sourceId);
        camera.image = std::move(*image);
        camera.width = static_cast<std::uint32_t>(width);
        camera.height = static_cast<std::uint32_t>(height);
        std::ranges::copy(*intrinsics, camera.intrinsics.begin());
        std::ranges::copy(*transform, camera.cameraToWorld.begin());
        camera.confidence = confidence;
        std::uint64_t timestamp{};
        const auto timestampError = element["timestampNanoseconds"].get(timestamp);
        if (!timestampError)
            camera.timestampNanoseconds = timestamp;
        else if (timestampError != simdjson::NO_SUCH_FIELD)
            return fail(ErrorCode::corruptData, "Canonical camera timestamp is invalid", camera.id);
        rig.cameras.push_back(std::move(camera));
    }
    if (auto validated = validateRig(rig, limits.maximumCameras); !validated)
        return std::unexpected(validated.error());
    return rig;
}

Result<void> validateSelfContainedGlb(std::span<const std::byte> bytes) {
    constexpr std::uint32_t glbMagic = 0x46546c67U;
    constexpr std::uint32_t jsonChunk = 0x4e4f534aU;
    if (bytes.size() < 20 || read32(bytes.data()) != glbMagic || read32(bytes.data() + 4) != 2 ||
        read32(bytes.data() + 8) != bytes.size())
        return fail(ErrorCode::corruptData, "Canonical mesh is not a complete glTF 2 GLB");
    const std::uint32_t jsonBytes = read32(bytes.data() + 12);
    if (read32(bytes.data() + 16) != jsonChunk || jsonBytes == 0 ||
        jsonBytes > maximumGlbJsonBytes || jsonBytes > bytes.size() - 20)
        return fail(ErrorCode::corruptData, "Canonical GLB JSON chunk is invalid");
    std::size_t logicalJsonBytes = jsonBytes;
    while (logicalJsonBytes > 0 && (bytes[20 + logicalJsonBytes - 1] == std::byte{' '} ||
                                    bytes[20 + logicalJsonBytes - 1] == std::byte{0}))
        --logicalJsonBytes;
    simdjson::dom::parser parser;
    simdjson::padded_string json(reinterpret_cast<const char*>(bytes.data() + 20),
                                 logicalJsonBytes);
    auto parsed = parser.parse(json);
    if (parsed.error())
        return fail(ErrorCode::corruptData, "Canonical GLB JSON cannot be parsed",
                    simdjson::error_message(parsed.error()));
    const auto rejectExternalUris = [](simdjson::dom::element document,
                                       const char* collection) -> Result<void> {
        simdjson::dom::array elements;
        const auto collectionError = document[collection].get_array().get(elements);
        if (collectionError == simdjson::NO_SUCH_FIELD)
            return {};
        if (collectionError)
            return fail(ErrorCode::corruptData, "Canonical GLB collection is invalid", collection);
        for (const auto element : elements) {
            std::string_view uri;
            const auto uriError = element["uri"].get_string().get(uri);
            if (!uriError && !uri.starts_with("data:"))
                return fail(ErrorCode::unsupported,
                            "Canonical GLB must embed buffers and images; external URI found",
                            std::string(uri));
            if (uriError != simdjson::SUCCESS && uriError != simdjson::NO_SUCH_FIELD)
                return fail(ErrorCode::corruptData, "Canonical GLB URI is invalid", collection);
        }
        return {};
    };
    if (auto buffers = rejectExternalUris(parsed.value(), "buffers"); !buffers)
        return buffers;
    return rejectExternalUris(parsed.value(), "images");
}

struct StringReference final {
    std::uint64_t offset{};
    std::uint32_t bytes{};
};

Result<StringReference> appendString(std::vector<std::byte>& table, std::string_view value) {
    if (value.empty() || value.size() > std::numeric_limits<std::uint32_t>::max() ||
        table.size() > maximumStringBytes - value.size())
        return fail(ErrorCode::resourceExhausted,
                    "Canonical camera string table exceeds its limit");
    const StringReference reference{table.size(), static_cast<std::uint32_t>(value.size())};
    for (const char character : value)
        table.push_back(static_cast<std::byte>(static_cast<unsigned char>(character)));
    return reference;
}

Result<std::string> readString(std::span<const std::byte> table, std::uint64_t offset,
                               std::uint32_t bytes) {
    if (bytes == 0 || offset > table.size() || bytes > table.size() - offset)
        return fail(ErrorCode::corruptData, "Canonical camera string reference is invalid");
    const auto* start = table.data() + static_cast<std::size_t>(offset);
    return std::string(reinterpret_cast<const char*>(start), bytes);
}

} // namespace

Result<std::vector<std::byte>> CameraRigCodec::encode(const CameraRig& rig) {
    if (auto validated = validateRig(rig, 1'000'000); !validated)
        return std::unexpected(validated.error());
    std::vector<std::byte> records;
    std::vector<std::byte> strings;
    records.reserve(rig.cameras.size() * recordBytes);
    for (const auto& camera : rig.cameras) {
        auto id = appendString(strings, camera.id);
        auto source = appendString(strings, camera.sourceId);
        auto image = appendString(strings, camera.image.generic_string());
        if (!id)
            return std::unexpected(id.error());
        if (!source)
            return std::unexpected(source.error());
        if (!image)
            return std::unexpected(image.error());
        for (const auto reference : {*id, *source, *image}) {
            append64(records, reference.offset);
            append32(records, reference.bytes);
        }
        append32(records, camera.width);
        append32(records, camera.height);
        for (const double value : camera.intrinsics)
            appendDouble(records, value);
        for (const double value : camera.cameraToWorld)
            appendDouble(records, value);
        append64(records, camera.timestampNanoseconds.value_or(missingTimestamp));
        appendDouble(records, camera.confidence);
        append32(records, 0);
    }
    std::vector<std::byte> output;
    output.insert(output.end(), cameraMagic.begin(), cameraMagic.end());
    append16(output, 1);
    append16(output, 0);
    append32(output, recordBytes);
    append64(output, rig.cameras.size());
    append64(output, strings.size());
    output.resize(headerBytes, std::byte{0});
    output.insert(output.end(), records.begin(), records.end());
    output.insert(output.end(), strings.begin(), strings.end());
    return output;
}

Result<CameraRig> CameraRigCodec::decode(std::span<const std::byte> bytes,
                                         std::size_t maximumCameras) {
    if (bytes.size() < headerBytes ||
        !std::equal(cameraMagic.begin(), cameraMagic.end(), bytes.begin()) ||
        read16(bytes.data() + 8) != 1 || read16(bytes.data() + 10) != 0 ||
        read32(bytes.data() + 12) != recordBytes)
        return fail(ErrorCode::corruptData, "Canonical camera chunk header is invalid");
    const std::uint64_t count = read64(bytes.data() + 16);
    const std::uint64_t stringBytes = read64(bytes.data() + 24);
    if (count == 0 || count > maximumCameras ||
        count > (std::numeric_limits<std::size_t>::max() - headerBytes) / recordBytes)
        return fail(ErrorCode::resourceExhausted, "Canonical camera chunk count is invalid");
    const std::size_t recordsBytes = static_cast<std::size_t>(count) * recordBytes;
    if (stringBytes > maximumStringBytes || stringBytes > bytes.size() ||
        headerBytes + recordsBytes > bytes.size() ||
        stringBytes != bytes.size() - headerBytes - recordsBytes)
        return fail(ErrorCode::corruptData, "Canonical camera chunk size is invalid");
    const auto strings = bytes.subspan(headerBytes + recordsBytes);
    CameraRig rig;
    rig.cameras.reserve(static_cast<std::size_t>(count));
    for (std::size_t index = 0; index < count; ++index) {
        const std::byte* record = bytes.data() + headerBytes + index * recordBytes;
        auto id = readString(strings, read64(record), read32(record + 8));
        auto source = readString(strings, read64(record + 12), read32(record + 20));
        auto image = readString(strings, read64(record + 24), read32(record + 32));
        if (!id)
            return std::unexpected(id.error());
        if (!source)
            return std::unexpected(source.error());
        if (!image)
            return std::unexpected(image.error());
        CameraRecord camera;
        camera.id = std::move(*id);
        camera.sourceId = std::move(*source);
        camera.image = std::move(*image);
        camera.width = read32(record + 36);
        camera.height = read32(record + 40);
        for (std::size_t component = 0; component < camera.intrinsics.size(); ++component)
            camera.intrinsics[component] = readDouble(record + 44 + component * 8);
        for (std::size_t component = 0; component < camera.cameraToWorld.size(); ++component)
            camera.cameraToWorld[component] = readDouble(record + 76 + component * 8);
        const auto timestamp = read64(record + 204);
        if (timestamp != missingTimestamp)
            camera.timestampNanoseconds = timestamp;
        camera.confidence = readDouble(record + 212);
        if (read32(record + 220) != 0)
            return fail(ErrorCode::corruptData,
                        "Canonical camera record reserved field is non-zero");
        rig.cameras.push_back(std::move(camera));
    }
    if (auto validated = validateRig(rig, maximumCameras); !validated)
        return std::unexpected(validated.error());
    return rig;
}

Result<std::vector<std::byte>> ConfidenceCodec::encode(std::span<const float> confidence) {
    if (confidence.empty())
        return fail(ErrorCode::invalidArgument, "Canonical confidence cannot be empty");
    if (std::ranges::any_of(confidence, [](float value) {
            return !std::isfinite(value) || value < 0.0F || value > 1.0F;
        }))
        return fail(ErrorCode::invalidArgument, "Canonical confidence contains an invalid value");
    std::vector<std::byte> output;
    output.insert(output.end(), confidenceMagic.begin(), confidenceMagic.end());
    append16(output, 1);
    append16(output, 0);
    append32(output, sizeof(float));
    append64(output, confidence.size());
    append64(output, 0);
    output.reserve(headerBytes + confidence.size() * sizeof(float));
    for (const float value : confidence)
        appendFloat(output, value);
    return output;
}

Result<std::vector<float>> ConfidenceCodec::decode(std::span<const std::byte> bytes,
                                                   std::size_t maximumVertices) {
    if (bytes.size() < headerBytes ||
        !std::equal(confidenceMagic.begin(), confidenceMagic.end(), bytes.begin()) ||
        read16(bytes.data() + 8) != 1 || read16(bytes.data() + 10) != 0 ||
        read32(bytes.data() + 12) != sizeof(float) || read64(bytes.data() + 24) != 0)
        return fail(ErrorCode::corruptData, "Canonical confidence chunk header is invalid");
    const std::uint64_t count = read64(bytes.data() + 16);
    if (count == 0 || count > maximumVertices ||
        count > (bytes.size() - headerBytes) / sizeof(float) ||
        bytes.size() != headerBytes + count * sizeof(float))
        return fail(ErrorCode::resourceExhausted, "Canonical confidence chunk size is invalid");
    std::vector<float> result(static_cast<std::size_t>(count));
    for (std::size_t index = 0; index < result.size(); ++index)
        result[index] = readFloat(bytes.data() + headerBytes + index * sizeof(float));
    if (std::ranges::any_of(result, [](float value) {
            return !std::isfinite(value) || value < 0.0F || value > 1.0F;
        }))
        return fail(ErrorCode::corruptData, "Canonical confidence contains an invalid value");
    return result;
}

Result<CanonicalAssetPayload> CanonicalAssetLoader::load(const std::filesystem::path& directory,
                                                         const CanonicalAssetLimits& limits) {
    std::error_code error;
    if (!std::filesystem::is_directory(directory, error) || error)
        return fail(ErrorCode::notFound, "Canonical asset root is not a directory", directory);
    auto manifestBytes = readFile(directory / "canonical-asset.json", limits.maximumManifestBytes);
    if (!manifestBytes)
        return std::unexpected(manifestBytes.error());
    auto manifest = parseManifestBytes(*manifestBytes);
    if (!manifest)
        return std::unexpected(manifest.error());
    auto resolvedMesh = containedFile(directory, manifest->mesh);
    auto resolvedCameras = containedFile(directory, manifest->cameras);
    if (!resolvedMesh)
        return std::unexpected(resolvedMesh.error());
    if (!resolvedCameras)
        return std::unexpected(resolvedCameras.error());
    const auto& meshPath = *resolvedMesh;
    auto meshBytes = readFile(meshPath, limits.maximumMeshBytes);
    if (!meshBytes)
        return std::unexpected(meshBytes.error());
    if (auto selfContained = validateSelfContainedGlb(*meshBytes); !selfContained)
        return std::unexpected(selfContained.error());
    mesh::GltfLimits meshLimits;
    meshLimits.maximumFileBytes = limits.maximumMeshBytes;
    meshLimits.maximumVertices = limits.maximumVertices;
    auto meshAsset = mesh::GltfLoader::load(meshPath, meshLimits);
    if (!meshAsset)
        return std::unexpected(meshAsset.error());
    const bool hasBoundTexture =
        std::ranges::any_of(meshAsset->materials, [](const auto& material) {
            return material.baseColorTexture || material.metallicRoughnessTexture ||
                   material.normalTexture || material.occlusionTexture || material.emissiveTexture;
        });
    if (meshAsset->images.empty() || meshAsset->textures.empty() || !hasBoundTexture)
        return fail(ErrorCode::corruptData,
                    "Canonical Asset v1 requires an embedded, material-bound texture");
    auto cameras = loadCameraJson(*resolvedCameras, limits);
    if (!cameras)
        return std::unexpected(cameras.error());
    auto cameraBytes = CameraRigCodec::encode(*cameras);
    if (!cameraBytes)
        return std::unexpected(cameraBytes.error());

    const std::size_t vertexCount = meshAsset->vertexCount();
    std::vector<std::byte> confidenceBytes;
    if (manifest->confidenceSource == ConfidenceSource::uniform) {
        const std::vector<float> confidence(vertexCount, manifest->uniformConfidence);
        auto encoded = ConfidenceCodec::encode(confidence);
        if (!encoded)
            return std::unexpected(encoded.error());
        confidenceBytes = std::move(*encoded);
    } else {
        auto resolvedConfidence = containedFile(directory, manifest->confidence);
        if (!resolvedConfidence)
            return std::unexpected(resolvedConfidence.error());
        if (limits.maximumVertices >
            (std::numeric_limits<std::uintmax_t>::max() - ConfidenceCodec::headerBytes) /
                sizeof(float))
            return fail(ErrorCode::invalidArgument,
                        "Canonical confidence allocation limit overflows byte addressing");
        const auto maximumConfidenceBytes =
            ConfidenceCodec::headerBytes + limits.maximumVertices * sizeof(float);
        auto encoded = readFile(*resolvedConfidence, maximumConfidenceBytes);
        if (!encoded)
            return std::unexpected(encoded.error());
        auto decoded = ConfidenceCodec::decode(*encoded, limits.maximumVertices);
        if (!decoded)
            return std::unexpected(decoded.error());
        if (decoded->size() != vertexCount)
            return fail(ErrorCode::corruptData,
                        "Canonical confidence count does not match canonical mesh vertices");
        confidenceBytes = std::move(*encoded);
    }

    CanonicalAssetPayload payload;
    payload.manifest = std::move(*manifest);
    payload.manifestBytes = std::move(*manifestBytes);
    payload.meshBytes = std::move(*meshBytes);
    payload.cameraBytes = std::move(*cameraBytes);
    payload.confidenceBytes = std::move(confidenceBytes);
    payload.cameraCount = cameras->cameras.size();
    payload.vertexCount = vertexCount;
    payload.triangleCount = meshAsset->indexCount() / 3;
    payload.materialCount = meshAsset->materials.size();
    payload.imageCount = meshAsset->images.size();
    return payload;
}

Result<CanonicalManifest> CanonicalAssetLoader::parseManifest(std::span<const std::byte> bytes) {
    return parseManifestBytes(bytes);
}

Result<CanonicalMeshSummary>
CanonicalAssetLoader::validateMeshPayload(std::span<const std::byte> bytes,
                                          const CanonicalAssetLimits& limits) {
    if (auto selfContained = validateSelfContainedGlb(bytes); !selfContained)
        return std::unexpected(selfContained.error());
    mesh::GltfLimits meshLimits;
    meshLimits.maximumFileBytes = limits.maximumMeshBytes;
    meshLimits.maximumVertices = limits.maximumVertices;
    auto meshAsset = mesh::GltfLoader::load(bytes, "canonical-mesh", meshLimits);
    if (!meshAsset)
        return std::unexpected(meshAsset.error());
    const bool hasBoundTexture =
        std::ranges::any_of(meshAsset->materials, [](const auto& material) {
            return material.baseColorTexture || material.metallicRoughnessTexture ||
                   material.normalTexture || material.occlusionTexture || material.emissiveTexture;
        });
    if (meshAsset->images.empty() || meshAsset->textures.empty() || !hasBoundTexture)
        return fail(ErrorCode::corruptData,
                    "Canonical Asset v1 requires an embedded, material-bound texture");
    return CanonicalMeshSummary{.vertexCount = meshAsset->vertexCount(),
                                .triangleCount = meshAsset->indexCount() / 3,
                                .materialCount = meshAsset->materials.size(),
                                .imageCount = meshAsset->images.size()};
}

} // namespace aether::canonical
