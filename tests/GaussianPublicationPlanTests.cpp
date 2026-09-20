#include <aether/gaussian/GaussianUpdatePlan.hpp>

#include <array>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testCoalescesMinimalRanges() {
    constexpr std::array<std::uint32_t, 7> indices{9, 2, 4, 3, 20, 21, 22};
    auto plan = aether::gaussian::planGaussianPublication(indices, 100, 256);
    expect(plan.has_value(), "valid Gaussian publication plan must succeed");
    if (!plan)
        return;
    expect(plan->ranges.size() == 3, "contiguous Gaussian IDs must coalesce into three ranges");
    expect(plan->ranges[0].firstIndex == 2 && plan->ranges[0].count == 3,
           "first coalesced range must be [2,5)");
    expect(plan->ranges[1].firstIndex == 9 && plan->ranges[1].count == 1,
           "second range must preserve isolated primitive");
    expect(plan->ranges[2].firstIndex == 20 && plan->ranges[2].count == 3,
           "third coalesced range must be [20,23)");
    expect(plan->touchedRecords == indices.size(), "touched-record accounting must be exact");
    expect(plan->touchedBytes == indices.size() * 256,
           "touched-byte accounting must use GPU record stride");
    expect(plan->fullBufferBytes == 100 * 256,
           "full-buffer byte baseline must use the same GPU record stride");
}

void testEmptyIsZeroWork() {
    auto plan = aether::gaussian::planGaussianPublication({}, 100, 128);
    expect(plan.has_value() && plan->ranges.empty() && plan->touchedBytes == 0,
           "empty Gaussian update must produce zero publication work");
    expect(plan.has_value() && plan->fullBufferBytes == 12'800,
           "empty update must retain the full-buffer reference denominator");
}

void testRejectsAmbiguousOrUnsafeInputs() {
    constexpr std::array<std::uint32_t, 2> duplicate{4, 4};
    constexpr std::array<std::uint32_t, 1> outside{100};
    expect(!aether::gaussian::planGaussianPublication(duplicate, 100, 256).has_value(),
           "duplicate Gaussian IDs must fail closed");
    expect(!aether::gaussian::planGaussianPublication(outside, 100, 256).has_value(),
           "out-of-range Gaussian ID must fail closed");
    expect(!aether::gaussian::planGaussianPublication({}, 100, 0).has_value(),
           "zero GPU record stride must fail closed");
    expect(!aether::gaussian::planGaussianPublication(
                {}, std::numeric_limits<std::size_t>::max(), 2)
                .has_value(),
           "full-buffer byte overflow must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testCoalescesMinimalRanges();
        testEmptyIsZeroWork();
        testRejectsAmbiguousOrUnsafeInputs();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian publication planner tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
