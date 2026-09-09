#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <vector>

namespace {

using aether::world::EntityId;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianOwnershipCodec;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void write32(std::vector<std::byte>& bytes, std::size_t offset, std::uint32_t value) {
    for (std::uint32_t index = 0; index < 4; ++index)
        bytes[offset + index] = static_cast<std::byte>((value >> (index * 8U)) & 0xffU);
}

void testRoundTripPreservesStableOwnership() {
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{}, EntityId{42}, EntityId{42}, EntityId{9001}};

    const auto encoded = GaussianOwnershipCodec::encode(ownership);
    expect(encoded.has_value(), "valid Gaussian ownership must encode");
    if (!encoded)
        return;
    expect(encoded->size() == GaussianOwnershipCodec::headerBytes + ownership.owners.size() * 8,
           "ownership sidecar must use fixed header plus one uint64 per Gaussian");

    const auto decoded = GaussianOwnershipCodec::decode(*encoded);
    expect(decoded.has_value(), "encoded ownership sidecar must decode");
    if (!decoded)
        return;
    expect(decoded->owners == ownership.owners,
           "ownership codec must preserve stable and unassigned entity IDs exactly");
}

void testCorruptionAndSchemaFailClosed() {
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{2}};
    auto encoded = GaussianOwnershipCodec::encode(ownership);
    if (!encoded) {
        expect(false, "corruption fixture must encode ownership");
        return;
    }

    auto badMagic = *encoded;
    badMagic[0] = std::byte{0};
    expect(!GaussianOwnershipCodec::decode(badMagic).has_value(),
           "ownership codec must reject invalid magic");

    auto badSchema = *encoded;
    write32(badSchema, 8, 999);
    expect(!GaussianOwnershipCodec::decode(badSchema).has_value(),
           "ownership codec must reject unsupported schema version");

    auto truncated = *encoded;
    truncated.pop_back();
    expect(!GaussianOwnershipCodec::decode(truncated).has_value(),
           "ownership codec must reject inconsistent payload byte count");
}

void testResourceLimitIsEnforcedBeforeAllocation() {
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{2}, EntityId{3}};
    const auto encoded = GaussianOwnershipCodec::encode(ownership);
    if (!encoded) {
        expect(false, "resource fixture must encode ownership");
        return;
    }
    expect(!GaussianOwnershipCodec::decode(*encoded, 2).has_value(),
           "ownership decode must reject count above caller allocation limit");
    expect(!GaussianOwnershipCodec::decode(*encoded, 0).has_value(),
           "ownership decode must reject a zero allocation limit");
}

} // namespace

int main() noexcept {
    try {
        testRoundTripPreservesStableOwnership();
        testCorruptionAndSchemaFailClosed();
        testResourceLimitIsEnforcedBeforeAllocation();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian ownership codec tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
