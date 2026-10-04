#include <aether/package/Package.hpp>

#include <zstd.h>

#include <algorithm>
#include <array>
#include <fstream>
#include <limits>
#include <set>

namespace aether::package {
namespace {

constexpr std::array<std::byte, 8> magic{std::byte{'A'}, std::byte{'E'}, std::byte{'T'},
                                         std::byte{'H'}, std::byte{'E'}, std::byte{'R'},
                                         std::byte{0},   std::byte{0}};
constexpr std::size_t headerBytes = 64;
constexpr std::size_t entryBytes = 64;
constexpr std::uint32_t requiredFlag = 1U << 0U;
constexpr std::uint32_t zstdFlag = 1U << 1U;
constexpr std::uint64_t maximumWriterCompressionRatio = 256;

void append16(std::vector<std::byte>& output, std::uint16_t value) {
    output.push_back(static_cast<std::byte>(value & 0xffU));
    output.push_back(static_cast<std::byte>((value >> 8U) & 0xffU));
}

void append32(std::vector<std::byte>& output, std::uint32_t value) {
    for (std::uint32_t shift = 0; shift < 32; shift += 8) {
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
    }
}

void append64(std::vector<std::byte>& output, std::uint64_t value) {
    for (std::uint32_t shift = 0; shift < 64; shift += 8) {
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
    }
}

std::uint16_t read16(const std::byte* bytes) {
    return static_cast<std::uint16_t>(std::to_integer<std::uint16_t>(bytes[0]) |
                                      (std::to_integer<std::uint16_t>(bytes[1]) << 8U));
}

std::uint32_t read32(const std::byte* bytes) {
    std::uint32_t result = 0;
    for (std::uint32_t index = 0; index < 4; ++index) {
        result |= std::to_integer<std::uint32_t>(bytes[index]) << (index * 8U);
    }
    return result;
}

std::uint64_t read64(const std::byte* bytes) {
    std::uint64_t result = 0;
    for (std::uint32_t index = 0; index < 8; ++index) {
        result |= std::to_integer<std::uint64_t>(bytes[index]) << (index * 8U);
    }
    return result;
}

void align64(std::vector<std::byte>& bytes) {
    const std::size_t padding = (64U - (bytes.size() % 64U)) % 64U;
    bytes.insert(bytes.end(), padding, std::byte{0});
}

Result<std::vector<std::byte>> compress(std::span<const std::byte> input) {
    std::vector<std::byte> output(ZSTD_compressBound(input.size()));
    const std::size_t written =
        ZSTD_compress(output.data(), output.size(), input.data(), input.size(), 3);
    if (ZSTD_isError(written)) {
        return fail(ErrorCode::internal, "Zstandard compression failed",
                    ZSTD_getErrorName(written));
    }
    output.resize(written);
    return output;
}

Result<Sha256Digest> hashFileTail(std::ifstream& stream, std::uint64_t offset,
                                  std::uint64_t fileBytes) {
    stream.clear();
    stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    if (!stream)
        return fail(ErrorCode::io, "Unable to seek while hashing package");
    Sha256 hash;
    std::array<std::byte, std::size_t{1024} * 1024> buffer{};
    std::uint64_t remaining = fileBytes - offset;
    while (remaining > 0) {
        const std::size_t amount = static_cast<std::size_t>(
            std::min<std::uint64_t>(remaining, static_cast<std::uint64_t>(buffer.size())));
        stream.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(amount));
        if (stream.gcount() != static_cast<std::streamsize>(amount)) {
            return fail(ErrorCode::io, "Package ended while hashing content");
        }
        hash.update(std::span<const std::byte>(buffer.data(), amount));
        remaining -= amount;
    }
    return hash.finalize();
}

} // namespace

Result<void> PackageWriter::addChunk(ChunkType type, std::span<const std::byte> data, bool required,
                                     Compression compressionMode) {
    if (!isKnownChunkType(type)) {
        return fail(ErrorCode::invalidArgument, "Writer requires a registered AETHER chunk type");
    }
    if (data.empty()) {
        return fail(ErrorCode::invalidArgument, "AETHER chunks cannot be empty",
                    chunkTypeName(type));
    }
    if (std::ranges::any_of(chunks_,
                            [&](const PendingChunk& chunk) { return chunk.type == type; })) {
        return fail(ErrorCode::invalidArgument, "Duplicate AETHER chunk type", chunkTypeName(type));
    }
    chunks_.push_back(PendingChunk{type, required, compressionMode,
                                   std::vector<std::byte>(data.begin(), data.end())});
    return {};
}

Result<void> PackageWriter::write(const std::filesystem::path& destination) const {
    if (chunks_.empty() || destination.empty()) {
        return fail(ErrorCode::invalidArgument, "Package requires chunks and a destination");
    }
    if (chunks_.size() > std::numeric_limits<std::uint32_t>::max()) {
        return fail(ErrorCode::resourceExhausted, "Package chunk count exceeds format capacity");
    }

    std::vector<std::byte> body;
    std::vector<ChunkInfo> entries;
    entries.reserve(chunks_.size());
    for (const PendingChunk& chunk : chunks_) {
        align64(body);
        std::vector<std::byte> stored = chunk.bytes;
        Compression actualCompression = Compression::none;
        if (chunk.compression == Compression::zstd) {
            auto compressed = compress(chunk.bytes);
            if (!compressed)
                return std::unexpected(compressed.error());
            // Never emit a frame that the default reader would reject as a potential
            // decompression bomb. Extremely compressible chunks remain valid, but are
            // stored verbatim instead.
            const bool withinRatioLimit =
                !compressed->empty() &&
                chunk.bytes.size() / compressed->size() <= maximumWriterCompressionRatio;
            if (compressed->size() < stored.size() && withinRatioLimit) {
                stored = std::move(*compressed);
                actualCompression = Compression::zstd;
            }
        }
        const std::uint64_t offset = headerBytes + body.size();
        body.insert(body.end(), stored.begin(), stored.end());
        entries.push_back(ChunkInfo{chunk.type, chunk.required, actualCompression, offset,
                                    stored.size(), chunk.bytes.size(), Sha256::hash(chunk.bytes)});
    }
    align64(body);
    const std::uint64_t tableOffset = headerBytes + body.size();
    std::vector<std::byte> table;
    table.reserve(entries.size() * entryBytes);
    for (const ChunkInfo& entry : entries) {
        append32(table, static_cast<std::uint32_t>(entry.type));
        append32(table, (entry.required ? requiredFlag : 0U) |
                            (entry.compression == Compression::zstd ? zstdFlag : 0U));
        append64(table, entry.offset);
        append64(table, entry.storedBytes);
        append64(table, entry.uncompressedBytes);
        table.insert(table.end(), entry.hash.begin(), entry.hash.end());
    }
    body.insert(body.end(), table.begin(), table.end());
    const Sha256Digest contentHash = Sha256::hash(body);

    std::vector<std::byte> header;
    header.reserve(headerBytes);
    header.insert(header.end(), magic.begin(), magic.end());
    const bool hasCanonicalAsset = std::ranges::any_of(entries, [](const ChunkInfo& entry) {
        return entry.type == ChunkType::canonicalAsset || entry.type == ChunkType::canonicalMesh ||
               entry.type == ChunkType::canonicalConfidence;
    });
    append16(header, 1);
    append16(header, hasCanonicalAsset ? 1 : 0);
    append32(header, 0);
    append64(header, tableOffset);
    append32(header, static_cast<std::uint32_t>(entries.size()));
    append32(header, 0);
    header.insert(header.end(), contentHash.begin(), contentHash.end());

    const auto temporary = destination.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(header.data()),
                 static_cast<std::streamsize>(header.size()));
    stream.write(reinterpret_cast<const char*>(body.data()),
                 static_cast<std::streamsize>(body.size()));
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Failed while writing AETHER package", destination.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, destination, error);
    if (error) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to finalize AETHER package", error.message());
    }
    return {};
}

Result<PackageReader> PackageReader::open(const std::filesystem::path& path, PackageLimits limits) {
    std::error_code filesystemError;
    const std::uint64_t fileBytes = std::filesystem::file_size(path, filesystemError);
    if (filesystemError || fileBytes < headerBytes || fileBytes > limits.maximumFileBytes) {
        return fail(ErrorCode::corruptData, "AETHER package size is invalid", path.string());
    }
    std::ifstream stream(path, std::ios::binary);
    std::array<std::byte, headerBytes> header{};
    stream.read(reinterpret_cast<char*>(header.data()), header.size());
    if (!stream || !std::equal(magic.begin(), magic.end(), header.begin())) {
        return fail(ErrorCode::corruptData, "AETHER package magic is invalid", path.string());
    }
    const std::uint16_t major = read16(header.data() + 8);
    const std::uint16_t minor = read16(header.data() + 10);
    if (major != 1) {
        return fail(ErrorCode::unsupported, "Unsupported AETHER package major version");
    }
    const std::uint64_t tableOffset = read64(header.data() + 16);
    const std::uint32_t chunkCount = read32(header.data() + 24);
    if (chunkCount == 0 || chunkCount > limits.maximumChunks || tableOffset < headerBytes ||
        tableOffset > fileBytes ||
        static_cast<std::uint64_t>(chunkCount) > (fileBytes - tableOffset) / entryBytes) {
        return fail(ErrorCode::corruptData, "AETHER chunk table is outside the file");
    }
    Sha256Digest expectedContentHash{};
    std::copy_n(header.begin() + 32, expectedContentHash.size(), expectedContentHash.begin());
    auto actualContentHash = hashFileTail(stream, headerBytes, fileBytes);
    if (!actualContentHash || *actualContentHash != expectedContentHash) {
        return fail(ErrorCode::corruptData, "AETHER package content hash does not match");
    }

    stream.clear();
    stream.seekg(static_cast<std::streamoff>(tableOffset), std::ios::beg);
    std::vector<std::byte> table(static_cast<std::size_t>(chunkCount) * entryBytes);
    stream.read(reinterpret_cast<char*>(table.data()), static_cast<std::streamsize>(table.size()));
    if (!stream)
        return fail(ErrorCode::corruptData, "AETHER chunk table is truncated");

    PackageReader reader;
    reader.path_ = path;
    reader.limits_ = limits;
    reader.info_.majorVersion = major;
    reader.info_.minorVersion = minor;
    reader.info_.fileBytes = fileBytes;
    reader.info_.contentHash = expectedContentHash;
    std::set<std::uint32_t> seenTypes;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> ranges;
    for (std::uint32_t index = 0; index < chunkCount; ++index) {
        const std::byte* entry = table.data() + static_cast<std::size_t>(index) * entryBytes;
        const auto rawType = read32(entry);
        const auto type = static_cast<ChunkType>(rawType);
        const std::uint32_t flags = read32(entry + 4);
        const bool required = (flags & requiredFlag) != 0;
        if ((flags & ~(requiredFlag | zstdFlag)) != 0 || !seenTypes.insert(rawType).second) {
            return fail(ErrorCode::corruptData, "AETHER chunk flags or type uniqueness is invalid");
        }
        if (!isKnownChunkType(type) && required) {
            return fail(ErrorCode::unsupported, "Package contains an unknown required chunk");
        }
        ChunkInfo info;
        info.type = type;
        info.required = required;
        info.compression = (flags & zstdFlag) ? Compression::zstd : Compression::none;
        info.offset = read64(entry + 8);
        info.storedBytes = read64(entry + 16);
        info.uncompressedBytes = read64(entry + 24);
        std::copy_n(entry + 32, info.hash.size(), info.hash.begin());
        if (info.storedBytes == 0 || info.uncompressedBytes == 0 ||
            info.uncompressedBytes > limits.maximumChunkBytes || info.offset < headerBytes ||
            info.offset > tableOffset || info.storedBytes > tableOffset - info.offset) {
            return fail(ErrorCode::corruptData, "AETHER chunk bounds are invalid");
        }
        if (info.compression == Compression::none && info.storedBytes != info.uncompressedBytes) {
            return fail(ErrorCode::corruptData, "Uncompressed AETHER chunk sizes differ");
        }
        if (info.compression == Compression::zstd &&
            info.uncompressedBytes / info.storedBytes > limits.maximumCompressionRatio) {
            return fail(ErrorCode::resourceExhausted,
                        "AETHER chunk compression ratio exceeds limit");
        }
        ranges.emplace_back(info.offset, info.offset + info.storedBytes);
        reader.info_.chunks.push_back(info);
    }
    std::ranges::sort(ranges);
    for (std::size_t index = 1; index < ranges.size(); ++index) {
        if (ranges[index].first < ranges[index - 1].second) {
            return fail(ErrorCode::corruptData, "AETHER chunks overlap");
        }
    }
    return reader;
}

Result<std::vector<std::byte>> PackageReader::readChunk(ChunkType type) const {
    const auto iterator = std::ranges::find_if(
        info_.chunks, [&](const ChunkInfo& info) { return info.type == type; });
    if (iterator == info_.chunks.end()) {
        return fail(ErrorCode::notFound, "AETHER package does not contain requested chunk",
                    chunkTypeName(type));
    }
    std::ifstream stream(path_, std::ios::binary);
    stream.seekg(static_cast<std::streamoff>(iterator->offset), std::ios::beg);
    std::vector<std::byte> stored(static_cast<std::size_t>(iterator->storedBytes));
    stream.read(reinterpret_cast<char*>(stored.data()),
                static_cast<std::streamsize>(stored.size()));
    if (!stream)
        return fail(ErrorCode::io, "Unable to read AETHER chunk", chunkTypeName(type));

    std::vector<std::byte> output;
    if (iterator->compression == Compression::zstd) {
        output.resize(static_cast<std::size_t>(iterator->uncompressedBytes));
        const std::size_t written =
            ZSTD_decompress(output.data(), output.size(), stored.data(), stored.size());
        if (ZSTD_isError(written) || written != output.size()) {
            return fail(ErrorCode::corruptData, "AETHER chunk decompression failed",
                        ZSTD_isError(written) ? ZSTD_getErrorName(written) : chunkTypeName(type));
        }
    } else {
        output = std::move(stored);
    }
    if (Sha256::hash(output) != iterator->hash) {
        return fail(ErrorCode::corruptData, "AETHER chunk hash does not match",
                    chunkTypeName(type));
    }
    return output;
}

const char* chunkTypeName(ChunkType type) noexcept {
    switch (type) {
    case ChunkType::metadata:
        return "metadata";
    case ChunkType::cameras:
        return "cameras";
    case ChunkType::baseGaussians:
        return "base-gaussians";
    case ChunkType::materialGaussians:
        return "material-gaussians";
    case ChunkType::residuals:
        return "residuals";
    case ChunkType::clusterHierarchy:
        return "cluster-hierarchy";
    case ChunkType::proxyMesh:
        return "proxy-mesh";
    case ChunkType::textures:
        return "textures";
    case ChunkType::collision:
        return "collision";
    case ChunkType::thumbnail:
        return "thumbnail";
    case ChunkType::benchmarkPath:
        return "benchmark-path";
    case ChunkType::canonicalAsset:
        return "canonical-asset";
    case ChunkType::canonicalMesh:
        return "canonical-mesh";
    case ChunkType::canonicalConfidence:
        return "canonical-confidence";
    }
    return "unknown";
}

bool isKnownChunkType(ChunkType type) noexcept {
    return type >= ChunkType::metadata && type <= ChunkType::canonicalConfidence;
}

} // namespace aether::package
