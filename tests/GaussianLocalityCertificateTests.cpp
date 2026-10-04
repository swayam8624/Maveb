#include <aether/world_gaussian/GaussianLocalityCertificate.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <vector>

namespace {

using aether::gaussian::Gaussian;
using aether::world::Bounds;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

Gaussian isotropic(float x, float y, float z, float sigma, float opacityLogit = 0.0F) {
    Gaussian result;
    result.position = {x, y, z};
    const float logScale = std::log(sigma);
    result.logScale = {logScale, logScale, logScale};
    result.opacityLogit = opacityLogit;
    return result;
}

Bounds unitBox() {
    return Bounds{{-1.0F, -1.0F, -1.0F}, {1.0F, 1.0F, 1.0F}};
}

void testCenteredGaussianHasTinyOutsideTail() {
    const Gaussian primitive = isotropic(0.0F, 0.0F, 0.0F, 0.1F);
    const std::vector<Gaussian> before{primitive};
    const std::vector<Gaussian> after{primitive};
    const auto certificate =
        aether::world_gaussian::certifyGaussianDensityLocality(before, after, unitBox());
    expect(certificate.has_value(), "centered Gaussian locality certificate must succeed");
    if (!certificate)
        return;

    const double expected = std::exp(-50.0);
    expect(std::abs(certificate->outsideDensityBound - expected) < 1.0e-20,
           "before+after centered alpha=0.5 Gaussian should produce exp(-50) bound");
}

void testBoundaryProximityIncreasesBound() {
    const std::vector<Gaussian> centered{isotropic(0.0F, 0.0F, 0.0F, 0.1F)};
    const std::vector<Gaussian> nearBoundary{isotropic(0.9F, 0.0F, 0.0F, 0.1F)};

    const auto centerCertificate =
        aether::world_gaussian::certifyGaussianDensityLocality(centered, {}, unitBox());
    const auto boundaryCertificate =
        aether::world_gaussian::certifyGaussianDensityLocality(nearBoundary, {}, unitBox());
    expect(centerCertificate && boundaryCertificate,
           "boundary comparison certificates must succeed");
    if (!centerCertificate || !boundaryCertificate)
        return;
    expect(boundaryCertificate->outsideDensityBound >
               centerCertificate->outsideDensityBound * 1.0e10,
           "Gaussian close to edit boundary must have a much larger outside tail bound");
}

void testOutsideMeanFallsBackToOpacityBound() {
    const std::vector<Gaussian> changed{isotropic(1.1F, 0.0F, 0.0F, 0.1F)};
    const auto certificate =
        aether::world_gaussian::certifyGaussianDensityLocality(changed, {}, unitBox());
    expect(certificate.has_value(), "outside-mean certificate must remain conservative");
    if (!certificate)
        return;
    expect(std::abs(certificate->faceDensityBounds[1] - 0.5) < 1.0e-12,
           "Gaussian mean already outside maximum-X face must be bounded by peak opacity");
}

void testInvalidRotationFailsClosed() {
    Gaussian invalid = isotropic(0.0F, 0.0F, 0.0F, 0.1F);
    invalid.rotation = {2.0F, 0.0F, 0.0F, 0.0F};
    const std::vector<Gaussian> changed{invalid};
    expect(!aether::world_gaussian::certifyGaussianDensityLocality(changed, {}, unitBox()),
           "non-normalized Gaussian rotation must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testCenteredGaussianHasTinyOutsideTail();
        testBoundaryProximityIncreasesBound();
        testOutsideMeanFallsBackToOpacityBound();
        testInvalidRotationFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian locality certificate tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
