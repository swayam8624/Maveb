#include <aether/scene/TemporalRevisionCertificate.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <random>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

double clamp(double value, double low, double high) {
    return std::min(std::max(value, low), high);
}

void testProductionNinetyPercentHistoryWeight() {
    auto certificate = aether::scene::certifyTemporalRevision(
        0.02, 0.01, 0.03, 0.9, true);
    expect(certificate.has_value(), "stable temporal certificate must succeed");
    if (!certificate)
        return;
    expect(!certificate->requiresHardInvalidation,
           "stable validation must allow soft temporal propagation");
    expect(std::abs(certificate->resolvedOutputBound - 0.029) < 1.0e-12,
           "90% history blend must match conservative formula");
}

void testUnstableValidationRequiresHardInvalidation() {
    auto certificate = aether::scene::certifyTemporalRevision(
        0.02, 0.9, 0.9, 0.9, false);
    expect(certificate.has_value() && certificate->requiresHardInvalidation,
           "unstable reprojection/disocclusion must become HARD invalidation");
    expect(certificate.has_value() &&
               std::abs(certificate->resolvedOutputBound - 0.02) < 1.0e-12,
           "post-invalidation output bound must reduce to current-frame bound");
}

void testRandomizedClampAndBlendBound() {
    std::mt19937_64 rng(20260920);
    std::uniform_real_distribution<double> unit(0.0, 1.0);

    for (int trial = 0; trial < 50'000; ++trial) {
        const double oldCurrent = unit(rng);
        const double newCurrent = unit(rng);
        const double oldHistory = unit(rng);
        const double newHistory = unit(rng);

        double oldLow = unit(rng);
        double oldHigh = unit(rng);
        if (oldLow > oldHigh)
            std::swap(oldLow, oldHigh);
        double newLow = unit(rng);
        double newHigh = unit(rng);
        if (newLow > newHigh)
            std::swap(newLow, newHigh);

        const double w = unit(rng);
        const double oldResolved =
            (1.0 - w) * oldCurrent + w * clamp(oldHistory, oldLow, oldHigh);
        const double newResolved =
            (1.0 - w) * newCurrent + w * clamp(newHistory, newLow, newHigh);

        const double currentBound = std::abs(newCurrent - oldCurrent);
        const double historyBound = std::abs(newHistory - oldHistory);
        const double neighborhoodBound =
            std::max(std::abs(newLow - oldLow), std::abs(newHigh - oldHigh));

        auto certificate = aether::scene::certifyTemporalRevision(
            currentBound, historyBound, neighborhoodBound, w, true);
        expect(certificate.has_value(), "randomized temporal certificate must succeed");
        if (!certificate)
            return;

        const double actual = std::abs(newResolved - oldResolved);
        if (actual > certificate->resolvedOutputBound + 1.0e-12) {
            expect(false, "randomized clamp/blend trial exceeded temporal certificate");
            return;
        }
    }
}

void testGeometricHistoryDecay() {
    auto decay = aether::scene::temporalHistoryDecayBound(1.0, 0.9, 10);
    expect(decay.has_value(), "temporal decay bound must succeed");
    if (!decay)
        return;
    expect(std::abs(*decay - std::pow(0.9, 10.0)) < 1.0e-12,
           "stable temporal history must decay geometrically");
}

void testInvalidWeightFailsClosed() {
    expect(!aether::scene::certifyTemporalRevision(0.1, 0.1, 0.1, 1.1, true),
           "history weight outside [0,1] must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testProductionNinetyPercentHistoryWeight();
        testUnstableValidationRequiresHardInvalidation();
        testRandomizedClampAndBlendBound();
        testGeometricHistoryDecay();
        testInvalidWeightFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Temporal revision certificate tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
