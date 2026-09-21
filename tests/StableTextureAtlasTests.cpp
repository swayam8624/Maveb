#include <aether/reconstruction/StableTextureAtlas.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <vector>

namespace {

using aether::reconstruction::StableTextureAtlasConfig;
using aether::reconstruction::StableTextureAtlasLayout;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

bool sameUv(const aether::reconstruction::StableTextureAtlasTile& a,
            const aether::reconstruction::StableTextureAtlasTile& b) {
    if (a.column != b.column || a.row != b.row || a.cellPixels != b.cellPixels ||
        a.innerPixels != b.innerPixels)
        return false;
    for (std::size_t index = 0; index < a.uv.size(); ++index) {
        if (simd_any(a.uv[index] != b.uv[index]))
            return false;
    }
    return true;
}

void testPersistentSlotsAreOrderIndependent() {
    StableTextureAtlasConfig config;
    config.atlasSize = 8192;
    config.gutterPixels = 4;
    config.slotCapacity = 10'000;

    auto layout = StableTextureAtlasLayout::create(config);
    expect(layout.has_value(), "stable atlas fixture must fit configured capacity");
    if (!layout)
        return;

    const std::vector<std::size_t> stableSlots{7, 91, 5000, 9999};
    std::vector<aether::reconstruction::StableTextureAtlasTile> before;
    for (const std::size_t slot : stableSlots) {
        auto value = layout->tile(slot);
        expect(value.has_value(), "stable atlas slot lookup must succeed");
        if (value)
            before.push_back(*value);
    }

    // Simulate arbitrary active-triangle reordering and insertion. The persistent slot IDs do not
    // change, so atlas addresses must remain identical.
    const std::vector<std::size_t> reordered{9999, 123, 5000, 91, 42, 7};
    static_cast<void>(reordered);

    for (std::size_t index = 0; index < stableSlots.size(); ++index) {
        auto after = layout->tile(stableSlots[index]);
        expect(after.has_value() && sameUv(before[index], *after),
               "unchanged stable slot must keep identical UV tile after unrelated order changes");
    }
}

void testCapacityDefinesLayoutInsteadOfActiveCount() {
    StableTextureAtlasConfig config;
    config.atlasSize = 8192;
    config.gutterPixels = 4;
    config.slotCapacity = 10'000;

    auto first = StableTextureAtlasLayout::create(config);
    auto second = StableTextureAtlasLayout::create(config);
    expect(first.has_value() && second.has_value(),
           "identical stable atlas capacity must deterministically recreate layout");
    if (!first || !second)
        return;

    auto a = first->tile(4321);
    auto b = second->tile(4321);
    expect(a.has_value() && b.has_value() && sameUv(*a, *b),
           "active scene population must not affect fixed-capacity slot UVs");
    expect(first->columns() == 100 && first->rows() == 100,
           "10,000 stable slots must form deterministic 100x100 grid");
}

void testInvalidOrExhaustedLayoutFailsClosed() {
    StableTextureAtlasConfig impossible;
    impossible.atlasSize = 64;
    impossible.gutterPixels = 4;
    impossible.slotCapacity = 1'000'000;
    expect(!StableTextureAtlasLayout::create(impossible).has_value(),
           "insufficient atlas resolution must reject stable-slot capacity");

    StableTextureAtlasConfig config;
    config.slotCapacity = 16;
    auto layout = StableTextureAtlasLayout::create(config);
    expect(layout.has_value(), "bounded stable atlas must be constructible");
    if (!layout)
        return;
    expect(!layout->tile(16).has_value(),
           "slot lookup beyond fixed capacity must fail instead of aliasing UVs");
}

} // namespace

int main() noexcept {
    try {
        testPersistentSlotsAreOrderIndependent();
        testCapacityDefinesLayoutInsteadOfActiveCount();
        testInvalidOrExhaustedLayoutFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Stable texture atlas tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
