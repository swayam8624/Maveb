#pragma once

#include <aether/core/Error.hpp>
#include <aether/package/Sha256.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <vector>

namespace aether::package {

enum class ChunkType : std::uint32_t {
    metadata = 1,
    cameras = 2,
    baseGaussians = 3,
    materialGaussians = 4,
    residuals = 5,
    clusterHierarchy = 6,
    proxyMesh = 7,
    textures = 8,
    collision = 9,
    thumbnail = 10,
    benchmarkPath = 11,
    canonicalAsset = 12,
    canonicalMesh = 13,
    canonicalConfidence = 14,
};

enum class Compression { none, zstd };

struct PackageLimits final {
    std::uint64_t maximumFileBytes{64ULL * 1024ULL * 1024ULL * 1024ULL};
    std::uint64_t maximumChunkBytes{8ULL * 1024ULL * 1024ULL * 1024ULL};
    std::uint32_t maximumChunks{1'000'000};
    std::uint32_t maximumCompressionRatio{256};
};

struct ChunkInfo final {
    ChunkType type{};
    bool required{};
    Compression compression{Compression::none};
    std::uint64_t offset{};
    std::uint64_t storedBytes{};
    std::uint64_t uncompressedBytes{};
    Sha256Digest hash{};
};

struct PackageInfo final {
    std::uint16_t majorVersion{};
    std::uint16_t minorVersion{};
    std::uint64_t fileBytes{};
    Sha256Digest contentHash{};
    std::vector<ChunkInfo> chunks;
};

class PackageWriter final {
  public:
    [[nodiscard]] Result<void> addChunk(ChunkType type, std::span<const std::byte> data,
                                        bool required = true,
                                        Compression compression = Compression::zstd);
    [[nodiscard]] Result<void> write(const std::filesystem::path& destination) const;

  private:
    struct PendingChunk {
        ChunkType type;
        bool required;
        Compression compression;
        std::vector<std::byte> bytes;
    };
    std::vector<PendingChunk> chunks_;
};

class PackageReader final {
  public:
    [[nodiscard]] static Result<PackageReader> open(const std::filesystem::path& path,
                                                    PackageLimits limits = {});

    [[nodiscard]] const PackageInfo& info() const noexcept {
        return info_;
    }
    [[nodiscard]] Result<std::vector<std::byte>> readChunk(ChunkType type) const;

  private:
    std::filesystem::path path_;
    PackageLimits limits_;
    PackageInfo info_;
};

[[nodiscard]] const char* chunkTypeName(ChunkType type) noexcept;
[[nodiscard]] bool isKnownChunkType(ChunkType type) noexcept;

} // namespace aether::package
