#pragma once

#include <aether/core/Error.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace aether::canonical {

struct ProviderProvenance final {
    std::string name;
    std::string version;
    std::string inputSha256;
    std::string configurationSha256;
};

enum class ConfidenceSource { uniform, perVertex };

struct CanonicalManifest final {
    std::string name;
    std::string coordinateSystem;
    double metersPerUnit{1.0};
    std::filesystem::path mesh;
    std::filesystem::path cameras;
    ConfidenceSource confidenceSource{ConfidenceSource::uniform};
    float uniformConfidence{1.0F};
    std::filesystem::path confidence;
    ProviderProvenance geometryProvider;
    ProviderProvenance appearanceProvider;
};

struct CameraRecord final {
    std::string id;
    std::string sourceId;
    std::filesystem::path image;
    std::uint32_t width{};
    std::uint32_t height{};
    std::array<double, 4> intrinsics{};     // fx, fy, cx, cy in pixels.
    std::array<double, 16> cameraToWorld{}; // Column-major right-handed transform.
    std::optional<std::uint64_t> timestampNanoseconds;
    double confidence{1.0};
};

struct CameraRig final {
    std::vector<CameraRecord> cameras;
};

struct CanonicalAssetLimits final {
    std::uintmax_t maximumManifestBytes{1ULL * 1024ULL * 1024ULL};
    std::uintmax_t maximumCameraJsonBytes{256ULL * 1024ULL * 1024ULL};
    std::uintmax_t maximumMeshBytes{8ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumCameras{1'000'000};
    std::size_t maximumVertices{50'000'000};
};

struct CanonicalAssetPayload final {
    CanonicalManifest manifest;
    std::vector<std::byte> manifestBytes;
    std::vector<std::byte> meshBytes;
    std::vector<std::byte> cameraBytes;
    std::vector<std::byte> confidenceBytes;
    std::size_t cameraCount{};
    std::size_t vertexCount{};
    std::size_t triangleCount{};
    std::size_t materialCount{};
    std::size_t imageCount{};
};

struct CanonicalMeshSummary final {
    std::size_t vertexCount{};
    std::size_t triangleCount{};
    std::size_t materialCount{};
    std::size_t imageCount{};
};

class CameraRigCodec final {
  public:
    static constexpr std::size_t headerBytes = 64;
    static constexpr std::size_t recordBytes = 224;

    /// Input: calibrated cameras in the canonical right-handed, Y-up metre frame.
    /// Output: deterministic little-endian `cameras` chunk bytes.
    /// Task: preserve image identity, calibration, pose, time, and confidence without ABI coupling.
    [[nodiscard]] static Result<std::vector<std::byte>> encode(const CameraRig& rig);

    /// Input: untrusted canonical camera bytes and an allocation limit.
    /// Output: validated cameras with rigid camera-to-world transforms.
    /// Task: reject invalid offsets, strings, intrinsics, transforms, and duplicate identities.
    [[nodiscard]] static Result<CameraRig> decode(std::span<const std::byte> bytes,
                                                  std::size_t maximumCameras = 1'000'000);
};

class ConfidenceCodec final {
  public:
    static constexpr std::size_t headerBytes = 32;

    /// Input: one finite confidence value in `[0,1]` per canonical mesh vertex.
    /// Output: deterministic little-endian `canonical-confidence` chunk bytes.
    [[nodiscard]] static Result<std::vector<std::byte>> encode(std::span<const float> confidence);

    /// Input: untrusted canonical confidence bytes and an allocation limit.
    /// Output: exactly one validated float per canonical vertex.
    [[nodiscard]] static Result<std::vector<float>>
    decode(std::span<const std::byte> bytes, std::size_t maximumVertices = 50'000'000);
};

class CanonicalAssetLoader final {
  public:
    /// Input: untrusted `canonical-asset.json` bytes.
    /// Output: validated metric-frame, source-path, confidence, and provenance declarations.
    [[nodiscard]] static Result<CanonicalManifest> parseManifest(std::span<const std::byte> bytes);

    /// Input: untrusted canonical GLB bytes.
    /// Output: semantic counts only for a complete, self-contained, textured glTF 2 GLB.
    /// Task: apply the same renderable-mesh rules to unpacked inputs and package-resident bytes.
    [[nodiscard]] static Result<CanonicalMeshSummary>
    validateMeshPayload(std::span<const std::byte> bytes, const CanonicalAssetLimits& limits = {});

    /// Input: an unpacked directory containing `canonical-asset.json` and its relative inputs.
    /// Output: validated, package-ready manifest, self-contained GLB, cameras, and confidence.
    /// Task: establish one metric scene frame before packaging or downstream reconstruction work.
    [[nodiscard]] static Result<CanonicalAssetPayload>
    load(const std::filesystem::path& directory, const CanonicalAssetLimits& limits = {});
};

} // namespace aether::canonical
