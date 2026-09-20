#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <random>
#include <vector>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

struct Layer final {
    bool edited{};
    double alpha{};
    std::array<double, 3> color{};
    double depth{};
};

std::array<double, 3> render(std::vector<Layer> layers,
                             const std::array<double, 3>& background) {
    std::sort(layers.begin(), layers.end(),
              [](const Layer& a, const Layer& b) { return a.depth < b.depth; });
    double transmittance = 1.0;
    std::array<double, 3> output{};
    for (const Layer& layer : layers) {
        for (std::size_t channel = 0; channel < 3; ++channel)
            output[channel] += transmittance * layer.alpha * layer.color[channel];
        transmittance *= 1.0 - layer.alpha;
    }
    for (std::size_t channel = 0; channel < 3; ++channel)
        output[channel] += transmittance * background[channel];
    return output;
}

double linf(const std::array<double, 3>& a, const std::array<double, 3>& b) {
    double result{};
    for (std::size_t channel = 0; channel < 3; ++channel)
        result = std::max(result, std::abs(a[channel] - b[channel]));
    return result;
}

void testEffectiveAlphaMirrorsShaderThresholds() {
    auto outside = aether::world_gaussian::effectiveGaussianRendererAlpha(0.8, 9.01);
    expect(outside && *outside == 0.0, "distance beyond 3-sigma ellipse must contribute zero");

    auto clamped = aether::world_gaussian::effectiveGaussianRendererAlpha(1.0, 0.0);
    expect(clamped && std::abs(*clamped - 0.99) < 1.0e-12,
           "renderer alpha must clamp to 0.99");

    auto threshold = aether::world_gaussian::effectiveGaussianRendererAlpha(0.001, 0.0);
    expect(threshold && *threshold == 0.0,
           "sub-1/255 renderer alpha must be treated as zero");
}

void testOpacityMassIncludesBackgroundVisibilityChange() {
    const std::array before{0.5};
    const std::array<double, 0> after{};
    auto cert =
        aether::world_gaussian::certifyGaussianPixelRevision(before, after, 1.0);
    expect(cert.has_value(), "single-splat certificate must succeed");
    if (!cert)
        return;
    expect(std::abs(cert->rgbLInfBound - 0.5) < 1.0e-12,
           "removing alpha=0.5 foreground must allow 0.5 background visibility change");
}

void testRandomizedInterleavingsStayBelowCertificate() {
    std::mt19937_64 rng(20260920);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::uniform_real_distribution<double> depth(-3.0, 3.0);
    std::uniform_int_distribution<int> unchangedCount(0, 12);
    std::uniform_int_distribution<int> editedCount(1, 6);

    constexpr double colorCap = 2.5;
    for (int trial = 0; trial < 20'000; ++trial) {
        std::vector<Layer> unchanged;
        for (int i = 0; i < unchangedCount(rng); ++i) {
            unchanged.push_back({
                .edited = false,
                .alpha = 0.7 * unit(rng),
                .color = {colorCap * unit(rng), colorCap * unit(rng), colorCap * unit(rng)},
                .depth = depth(rng),
            });
        }

        std::vector<Layer> beforeEdited;
        std::vector<Layer> afterEdited;
        std::vector<double> beforeAlphas;
        std::vector<double> afterAlphas;

        for (int i = 0; i < editedCount(rng); ++i) {
            const double alpha = 0.4 * unit(rng);
            beforeAlphas.push_back(alpha);
            beforeEdited.push_back({
                .edited = true,
                .alpha = alpha,
                .color = {colorCap * unit(rng), colorCap * unit(rng), colorCap * unit(rng)},
                .depth = depth(rng),
            });
        }
        for (int i = 0; i < editedCount(rng); ++i) {
            const double alpha = 0.4 * unit(rng);
            afterAlphas.push_back(alpha);
            afterEdited.push_back({
                .edited = true,
                .alpha = alpha,
                .color = {colorCap * unit(rng), colorCap * unit(rng), colorCap * unit(rng)},
                .depth = depth(rng),
            });
        }

        std::array<double, 3> background{
            colorCap * unit(rng), colorCap * unit(rng), colorCap * unit(rng)};

        auto before = unchanged;
        before.insert(before.end(), beforeEdited.begin(), beforeEdited.end());
        auto after = unchanged;
        after.insert(after.end(), afterEdited.begin(), afterEdited.end());

        const double actual = linf(render(before, background), render(after, background));
        auto cert = aether::world_gaussian::certifyGaussianPixelRevision(
            beforeAlphas, afterAlphas, colorCap);
        expect(cert.has_value(), "randomized certificate must succeed");
        if (!cert)
            return;
        if (actual > cert->rgbLInfBound + 1.0e-11) {
            expect(false, "randomized compositing trial exceeded RGB certificate");
            return;
        }
    }
}

void testShColorUpperBoundDominatesSampledDirectionsDegreeZero() {
    aether::gaussian::Gaussian primitive;
    primitive.dc = {1.0F, -2.0F, 0.25F};
    primitive.restCount = 0;
    auto bound = aether::world_gaussian::gaussianRendererColorUpperBound(primitive);
    expect(bound.has_value(), "degree-zero SH upper bound must succeed");
    if (!bound)
        return;

    constexpr double c0 = 0.28209479177387814;
    expect((*bound)[0] >= 0.5 + c0,
           "degree-zero red upper bound must include absolute DC contribution");
    expect((*bound)[1] >= 0.5 + 2.0 * c0,
           "degree-zero green upper bound must include absolute DC contribution");
}

void testInvalidAlphaFailsClosed() {
    const std::array invalid{1.2};
    expect(!aether::world_gaussian::certifyGaussianPixelRevision(invalid, {}, 1.0),
           "alpha outside [0,1] must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testEffectiveAlphaMirrorsShaderThresholds();
        testOpacityMassIncludesBackgroundVisibilityChange();
        testRandomizedInterleavingsStayBelowCertificate();
        testShColorUpperBoundDominatesSampledDirectionsDegreeZero();
        testInvalidAlphaFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian render certificate tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
