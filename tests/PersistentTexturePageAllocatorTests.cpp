#include <aether/reconstruction/PersistentTexturePageAllocator.hpp>

#include <array>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <vector>

namespace {

using aether::reconstruction::PersistentTexturePageAllocator;
using aether::reconstruction::PersistentTexturePageConfig;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testLocalityPackingAndStableAddresses() {
    auto allocator = PersistentTexturePageAllocator::create(
        PersistentTexturePageConfig{.slotsPerPage = 8, .maximumPages = 16});
    expect(allocator.has_value(), "persistent texture page allocator must build");
    if (!allocator)
        return;

    std::array<aether::reconstruction::PersistentTexturePageAddress, 12> first{};
    for (std::uint64_t id = 1; id <= 12; ++id) {
        auto address = allocator->allocate(id, 100);
        expect(address.has_value(), "first locality allocation must succeed");
        if (address)
            first[id - 1] = *address;
    }
    for (std::uint64_t id = 101; id <= 112; ++id)
        expect(allocator->allocate(id, 200).has_value(), "second locality allocation must succeed");

    expect(first[0].page == first[7].page, "first eight same-locality patches must share one page");
    expect(first[8].page != first[0].page,
           "same locality must spill into a second page only after capacity");
    expect(allocator->address(1).has_value() && *allocator->address(1) == first[0],
           "unrelated locality allocation must not move existing stable address");

    const std::vector<std::uint64_t> changed{1, 2, 3, 4};
    const auto dirty = allocator->dirtyPages(changed);
    expect(dirty.size() == 1 && dirty.front() == first[0].page,
           "clustered patch changes must resolve to one exact dirty page");
}

void testHoleReuseWithoutGlobalChurn() {
    auto allocator = PersistentTexturePageAllocator::create(
        PersistentTexturePageConfig{.slotsPerPage = 4, .maximumPages = 8});
    if (!allocator)
        return;

    for (std::uint64_t id = 1; id <= 4; ++id)
        expect(allocator->allocate(id, 77).has_value(), "fixture allocation must succeed");
    const auto stable = allocator->address(4);
    const auto removed = allocator->address(2);
    expect(stable.has_value() && removed.has_value(), "fixture addresses must exist");
    if (!stable || !removed)
        return;

    expect(allocator->release(2).has_value(), "release must create a reusable hole");
    auto replacement = allocator->allocate(9, 77);
    expect(replacement.has_value() && *replacement == *removed,
           "same-locality insertion must deterministically reuse lowest free hole");
    expect(allocator->address(4).has_value() && *allocator->address(4) == *stable,
           "hole reuse must not renumber an unrelated stable patch");

    const auto stats = allocator->statistics();
    expect(stats.pageCount == 1 && stats.activeSlots == 4 && stats.freeSlots == 0,
           "hole reuse must restore one-page occupancy without extra allocation");
}

void testFragmentationAndBudgetsFailClosed() {
    auto allocator = PersistentTexturePageAllocator::create(
        PersistentTexturePageConfig{.slotsPerPage = 2, .maximumPages = 1});
    if (!allocator)
        return;

    expect(allocator->allocate(1, 5).has_value(), "first patch must allocate");
    expect(allocator->allocate(2, 5).has_value(), "second patch must allocate");
    expect(!allocator->allocate(3, 5).has_value(),
           "allocator must fail closed when maximum pages are exhausted");
    expect(allocator->release(1).has_value(), "release must succeed");
    const auto stats = allocator->statistics();
    expect(stats.activeSlots == 1 && stats.freeSlots == 1 && stats.fragmentation == 0.5,
           "allocator must expose exact retained-page fragmentation");
    expect(!allocator->allocate(2, 6).has_value(),
           "existing patch cannot silently migrate between locality keys");
}

} // namespace

int main() noexcept {
    try {
        testLocalityPackingAndStableAddresses();
        testHoleReuseWithoutGlobalChurn();
        testFragmentationAndBudgetsFailClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Persistent texture page allocator tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
