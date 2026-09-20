#include <aether/scene/TemporalInvalidation.hpp>

#include <cstdlib>
#include <exception>
#include <iostream>
#include <simd/simd.h>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testCompactVisibleRegion() {
    aether::scene::TemporalWorldBounds bounds{{-0.1F, -0.1F, 0.2F},
                                              {0.1F, 0.1F, 0.4F}};
    auto plan = aether::scene::planTemporalInvalidation(
        bounds, matrix_identity_float4x4, 1000, 1000, 0);
    expect(plan.has_value(), "visible temporal invalidation plan must succeed");
    if (!plan)
        return;
    expect(!plan->fullFrame && !plan->empty,
           "compact visible bounds must use a regional invalidation");
    expect(plan->pixelRatio() > 0.0 && plan->pixelRatio() < 0.1,
           "compact visible bounds must invalidate a small screen fraction");
}

void testOffscreenRegionIsEmpty() {
    aether::scene::TemporalWorldBounds bounds{{3.0F, 3.0F, 0.2F},
                                              {4.0F, 4.0F, 0.4F}};
    auto plan = aether::scene::planTemporalInvalidation(
        bounds, matrix_identity_float4x4, 640, 480, 0);
    expect(plan.has_value() && plan->empty && plan->invalidatedPixels == 0,
           "fully off-screen bounds must preserve all temporal history");
}

void testUnsafeProjectionFallsBackToFullFrame() {
    auto matrix = matrix_identity_float4x4;
    matrix.columns[3].w = -2.0F;
    aether::scene::TemporalWorldBounds bounds{{-0.1F, -0.1F, -1.0F},
                                              {0.1F, 0.1F, 1.0F}};
    auto plan = aether::scene::planTemporalInvalidation(bounds, matrix, 320, 200, 4);
    expect(plan.has_value() && plan->fullFrame,
           "unsafe camera-plane projection must fail safe to full-frame invalidation");
    expect(plan.has_value() && plan->invalidatedPixels == 64'000,
           "full-frame fallback must account exact invalidated pixels");
}

void testExpansionIncreasesArea() {
    aether::scene::TemporalWorldBounds bounds{{-0.2F, -0.2F, 0.2F},
                                              {0.2F, 0.2F, 0.4F}};
    auto tight = aether::scene::planTemporalInvalidation(
        bounds, matrix_identity_float4x4, 800, 600, 0);
    auto expanded = aether::scene::planTemporalInvalidation(
        bounds, matrix_identity_float4x4, 800, 600, 8);
    expect(tight.has_value() && expanded.has_value() &&
               expanded->invalidatedPixels > tight->invalidatedPixels,
           "safety expansion must conservatively increase invalidated area");
}

} // namespace

int main() noexcept {
    try {
        testCompactVisibleRegion();
        testOffscreenRegionIsEmpty();
        testUnsafeProjectionFallsBackToFullFrame();
        testExpansionIncreasesArea();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Temporal invalidation tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
