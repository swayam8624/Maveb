#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>

namespace aether::world_gaussian {
namespace {

constexpr std::array<std::byte, 8> ownershipMagic{
    std::byte{'M'}, std::byte{'V'}, std::byte{'G'}, std::byte{'O'},
    std::byte{'W'}, std::byte{'N'}, std::byte{'R'}, std::byte{0},
};

void append32(std::vector<std::byte>& output, std::uint32_t value) {
    for (std::uint32_t shift = 0; shift < 32; shift += 8)
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
}

void append64(std::vector<std::byte>& output, std::uint64_t value) {
    for (std::uint32_t shift = 0; shift < 64; shift += 8)
        output.push_back(static_cast<std::byte>((value >> shift) & 0xffU));
}

[[nodiscard]] std::uint32_t read32(const std::byte* bytes) noexcept {
    std::uint32_t value{};
    for (std::uint32_t index = 0; index < 4; ++index)
        value |= std::to_integer<std::uint32_t>(bytes[index]) << (index * 8U);
    return value;
}

[[nodiscard]] std::uint64_t read64(const std::byte* bytes) noexcept {
    std::uint64_t value{};
    for (std::uint32_t index = 0; index < 8; ++index)
        value |= std::to_integer<std::uint64_t>(bytes[index]) << (index * 8U);
    return value;
}

} // namespace

Result<std::vector<std::byte>>
GaussianOwnershipCodec::encode(const GaussianEntityOwnership& ownership) {
    constexpr std::size_t bytesPerOwner = sizeof(std::uint64_t);
    if (ownership.owners.size() >
        (std::numeric_limits<std::size_t>::max() - headerBytes) / bytesPerOwner) {
        return fail(ErrorCode::resourceExhausted, "Gaussian ownership sidecar size overflows memory");
    }

    const std::size_t outputBytes = headerBytes + ownership.owners.size() * bytesPerOwner;
    std::vector<std::byte> output;
    output.reserve(outputBytes);
    output.insert(output.end(), ownershipMagic.begin(), ownershipMagic.end());
    append32(output, schemaVersion);
    append32(output, static_cast<std::uint32_t>(headerBytes));
    append64(output, ownership.owners.size());
    append64(output, 0);
    for (const world::EntityId owner : ownership.owners)
        append64(output, owner.value);
    return output;
}

Result<GaussianEntityOwnership>
GaussianOwnershipCodec::decode(std::span<const std::byte> bytes, std::size_t maximumGaussians) {
    if (maximumGaussians == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian ownership decode limit cannot be zero");
    if (bytes.size() < headerBytes)
        return fail(ErrorCode::corruptData, "Gaussian ownership sidecar is truncated");
    if (!std::equal(ownershipMagic.begin(), ownershipMagic.end(), bytes.begin()))
        return fail(ErrorCode::corruptData, "Gaussian ownership sidecar magic is invalid");

    const std::uint32_t version = read32(bytes.data() + 8);
    const std::uint32_t encodedHeaderBytes = read32(bytes.data() + 12);
    const std::uint64_t encodedCount = read64(bytes.data() + 16);
    const std::uint64_t reserved = read64(bytes.data() + 24);
    if (version != schemaVersion)
        return fail(ErrorCode::unsupported, "Gaussian ownership sidecar schema is unsupported");
    if (encodedHeaderBytes != headerBytes || reserved != 0)
        return fail(ErrorCode::corruptData, "Gaussian ownership sidecar header is invalid");
    if (encodedCount > maximumGaussians || encodedCount > std::numeric_limits<std::size_t>::max())
        return fail(ErrorCode::resourceExhausted,
                    "Gaussian ownership sidecar exceeds primitive-count limit");

    const std::size_t count = static_cast<std::size_t>(encodedCount);
    constexpr std::size_t bytesPerOwner = sizeof(std::uint64_t);
    if (count > (std::numeric_limits<std::size_t>::max() - headerBytes) / bytesPerOwner)
        return fail(ErrorCode::resourceExhausted, "Gaussian ownership sidecar byte size overflows");
    const std::size_t expectedBytes = headerBytes + count * bytesPerOwner;
    if (bytes.size() != expectedBytes)
        return fail(ErrorCode::corruptData, "Gaussian ownership sidecar byte count is inconsistent");

    GaussianEntityOwnership ownership;
    ownership.owners.reserve(count);
    const std::byte* cursor = bytes.data() + headerBytes;
    for (std::size_t index = 0; index < count; ++index) {
        ownership.owners.push_back(world::EntityId{read64(cursor)});
        cursor += bytesPerOwner;
    }
    return ownership;
}

} // namespace aether::world_gaussian
