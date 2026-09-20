#include <aether/gaussian/ReferenceRasterizer.hpp>
#include <aether/world_gaussian/GaussianImageRevisionCertificate.hpp>
#include <aether/world_gaussian/GaussianRenderCertificate.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

aether::gaussian::Gaussian primitive(float x, float z,
                                     std::array<float, 3> dc,
                                     float opacityLogit = 1.5F) {
    aether::gaussian::Gaussian g;
    g.position = {x, 0.0F, z};
    const float scale = std::log(0.12F);
    g.logScale = {scale, scale, scale};
    g.opacityLogit = opacityLogit;
    g.dc = dc;
    return g;
}

aether::gaussian::ReferenceCamera camera() {
    aether::gaussian::ReferenceCamera c;
    c.width = 64;
    c.height = 64;
    c.focalX = 70.0F;
    c.focalY = 70.0F;
    c.centerX = 32.0F;
    c.centerY = 32.0F;
    c.nearPlane = 0.1F;
    c.farPlane = 100.0F;
    c.cameraWorldPosition = {0.0F, 0.0F, 0.0F};
    return c;
}

double sceneColorCap(const aether::gaussian::GaussianAsset& a,
                     const aether::gaussian::GaussianAsset& b,
                     const aether::gaussian::GaussianAsset& u) {
    double cap = 1.0; // reference background is clamped to [0,1]
    const auto visit = [&](const aether::gaussian::GaussianAsset& asset) {
        for (const auto& g : asset.gaussians) {
            auto bound =
                aether::world_gaussian::gaussianRendererColorUpperBound(g);
            if (!bound)
                return false;
            for (double channel : *bound)
                cap = std::max(cap, channel);
        }
        return true;
    };
    expect(visit(a) && visit(b) && visit(u),
           "scene color cap construction must succeed");
    return cap;
}

void testProjectedCertificateBoundsExactReferenceDifference() {
    aether::gaussian::GaussianAsset unchanged;
    unchanged.gaussians.push_back(
        primitive(0.0F, 4.0F, {0.0F, 0.0F, 1.0F}, 2.0F));

    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(
        primitive(-0.18F, 3.0F, {1.2F, 0.0F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset afterChanged;
    afterChanged.gaussians.push_back(
        primitive(0.22F, 3.0F, {0.0F, 1.2F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset oldFull = unchanged;
    oldFull.gaussians.insert(oldFull.gaussians.end(),
                             beforeChanged.gaussians.begin(),
                             beforeChanged.gaussians.end());
    aether::gaussian::GaussianAsset newFull = unchanged;
    newFull.gaussians.insert(newFull.gaussians.end(),
                             afterChanged.gaussians.begin(),
                             afterChanged.gaussians.end());

    const auto c = camera();
    const std::array<float, 3> background{0.15F, 0.2F, 0.25F};
    auto oldImage = aether::gaussian::ReferenceRasterizer::render(oldFull, c, background);
    auto newImage = aether::gaussian::ReferenceRasterizer::render(newFull, c, background);
    expect(oldImage && newImage, "reference images must render");
    if (!oldImage || !newImage)
        return;

    const double cap = sceneColorCap(beforeChanged, afterChanged, unchanged);
    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(
            beforeChanged, afterChanged, c, cap);
    expect(certificate.has_value(), "projected image certificate must succeed");
    if (!certificate)
        return;

    bool sawNonZero = false;
    bool sawLocalZero = false;
    for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual = std::max(
                actual,
                std::abs(static_cast<double>(oldImage->color[pixel][channel]) -
                         static_cast<double>(newImage->color[pixel][channel])));
        }
        const double bound = certificate->rgbLInfBounds[pixel];
        if (bound > 0.0)
            sawNonZero = true;
        else
            sawLocalZero = true;
        if (actual > bound + 2.0e-6) {
            expect(false,
                   "reference raster difference exceeded projected Gaussian certificate");
            return;
        }
    }
    expect(sawNonZero, "edited splats must create a non-zero certified image region");
    expect(sawLocalZero,
           "compact edited splats should leave some pixels exactly outside the certificate support");
}

void testEmptyEditedSetsGiveZeroImageBound() {
    aether::gaussian::GaussianAsset empty;
    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(
            empty, empty, camera(), 1.0);
    expect(certificate.has_value(), "empty edit certificate must succeed");
    if (!certificate)
        return;
    expect(certificate->maximumRgbLInfBound == 0.0,
           "empty edit must certify zero RGB change");
}

} // namespace

int main() noexcept {
    try {
        testProjectedCertificateBoundsExactReferenceDifference();
        testEmptyEditedSetsGiveZeroImageBound();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian image revision certificate tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
