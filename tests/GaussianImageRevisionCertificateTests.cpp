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

aether::gaussian::Gaussian primitive(float x, float z, std::array<float, 3> dc,
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
            auto bound = aether::world_gaussian::gaussianRendererColorUpperBound(g);
            if (!bound)
                return false;
            for (double channel : *bound)
                cap = std::max(cap, channel);
        }
        return true;
    };
    expect(visit(a) && visit(b) && visit(u), "scene color cap construction must succeed");
    return cap;
}

void testProjectedCertificateBoundsExactReferenceDifference() {
    aether::gaussian::GaussianAsset unchanged;
    unchanged.gaussians.push_back(primitive(0.0F, 4.0F, {0.0F, 0.0F, 1.0F}, 2.0F));

    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(primitive(-0.18F, 3.0F, {1.2F, 0.0F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset afterChanged;
    afterChanged.gaussians.push_back(primitive(0.22F, 3.0F, {0.0F, 1.2F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset oldFull = unchanged;
    oldFull.gaussians.insert(oldFull.gaussians.end(), beforeChanged.gaussians.begin(),
                             beforeChanged.gaussians.end());
    aether::gaussian::GaussianAsset newFull = unchanged;
    newFull.gaussians.insert(newFull.gaussians.end(), afterChanged.gaussians.begin(),
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
        aether::world_gaussian::certifyGaussianImageRevision(beforeChanged, afterChanged, c, cap);
    expect(certificate.has_value(), "projected image certificate must succeed");
    if (!certificate)
        return;

    bool sawNonZero = false;
    bool sawLocalZero = false;
    for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual =
                std::max(actual, std::abs(static_cast<double>(oldImage->color[pixel][channel]) -
                                          static_cast<double>(newImage->color[pixel][channel])));
        }
        const double bound = certificate->rgbLInfBounds[pixel];
        if (bound > 0.0)
            sawNonZero = true;
        else
            sawLocalZero = true;
        if (actual > bound + 2.0e-6) {
            expect(false, "reference raster difference exceeded projected Gaussian certificate");
            return;
        }
    }
    expect(sawNonZero, "edited splats must create a non-zero certified image region");
    expect(
        sawLocalZero,
        "compact edited splats should leave some pixels exactly outside the certificate support");
}

void testProjectedCertificateSupportsTranslatedCamera() {
    aether::gaussian::GaussianAsset unchanged;
    unchanged.gaussians.push_back(primitive(0.0F, 4.0F, {0.0F, 0.0F, 1.0F}, 2.0F));

    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(primitive(-0.05F, 3.0F, {1.0F, 0.0F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset afterChanged;
    afterChanged.gaussians.push_back(primitive(0.15F, 3.0F, {0.0F, 1.0F, 0.0F}, 2.0F));

    aether::gaussian::GaussianAsset oldFull = unchanged;
    oldFull.gaussians.insert(oldFull.gaussians.end(), beforeChanged.gaussians.begin(),
                             beforeChanged.gaussians.end());
    aether::gaussian::GaussianAsset newFull = unchanged;
    newFull.gaussians.insert(newFull.gaussians.end(), afterChanged.gaussians.begin(),
                             afterChanged.gaussians.end());

    auto c = camera();
    c.cameraWorldPosition = {0.25F, 0.0F, 0.0F};
    c.worldToCamera[3] = -0.25F;

    const std::array<float, 3> background{0.05F, 0.05F, 0.05F};
    auto oldImage = aether::gaussian::ReferenceRasterizer::render(oldFull, c, background);
    auto newImage = aether::gaussian::ReferenceRasterizer::render(newFull, c, background);
    expect(oldImage && newImage, "translated-camera reference images must render");
    if (!oldImage || !newImage)
        return;

    const double cap = sceneColorCap(beforeChanged, afterChanged, unchanged);
    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(beforeChanged, afterChanged, c, cap);
    expect(certificate.has_value(), "translated-camera projected certificate must succeed");
    if (!certificate)
        return;

    for (std::size_t pixel = 0; pixel < oldImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual =
                std::max(actual, std::abs(static_cast<double>(oldImage->color[pixel][channel]) -
                                          static_cast<double>(newImage->color[pixel][channel])));
        }
        if (actual > certificate->rgbLInfBounds[pixel] + 2.0e-6) {
            expect(false, "translated-camera reference difference exceeded certificate");
            return;
        }
    }
}

void testOpacityDeltaCertificateBoundsReferenceAndTightensSmallResidual() {
    aether::gaussian::GaussianAsset unchanged;
    unchanged.gaussians.push_back(primitive(0.0F, 4.0F, {0.2F, 0.4F, 0.8F}, 2.0F));

    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(primitive(0.0F, 3.0F, {1.0F, 0.2F, 0.1F}, 1.5005F));

    aether::gaussian::GaussianAsset afterChanged;
    afterChanged.gaussians.push_back(primitive(0.0F, 3.0F, {1.0F, 0.2F, 0.1F}, 1.5F));

    aether::gaussian::GaussianAsset beforeFull = unchanged;
    beforeFull.gaussians.insert(beforeFull.gaussians.end(), beforeChanged.gaussians.begin(),
                                beforeChanged.gaussians.end());
    aether::gaussian::GaussianAsset afterFull = unchanged;
    afterFull.gaussians.insert(afterFull.gaussians.end(), afterChanged.gaussians.begin(),
                               afterChanged.gaussians.end());

    const auto c = camera();
    const std::array<float, 3> background{0.1F, 0.1F, 0.1F};
    auto beforeImage = aether::gaussian::ReferenceRasterizer::render(beforeFull, c, background);
    auto afterImage = aether::gaussian::ReferenceRasterizer::render(afterFull, c, background);
    expect(beforeImage && afterImage, "opacity-delta reference images must render");
    if (!beforeImage || !afterImage)
        return;

    const double cap = sceneColorCap(beforeChanged, afterChanged, unchanged);
    auto coarse =
        aether::world_gaussian::certifyGaussianImageRevision(beforeChanged, afterChanged, c, cap);
    auto tight = aether::world_gaussian::certifyGaussianOpacityOnlyImageRevision(
        beforeChanged, afterChanged, c, cap);
    expect(coarse.has_value(), "coarse opacity certificate must succeed");
    expect(tight.has_value(), "opacity-delta certificate must succeed");
    if (!coarse || !tight)
        return;

    expect(tight->maximumRgbLInfBound < coarse->maximumRgbLInfBound,
           "small opacity residual should tighten the coarse opacity-envelope bound");

    bool sawCertifiedChange = false;
    for (std::size_t pixel = 0; pixel < beforeImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual =
                std::max(actual,
                         std::abs(static_cast<double>(beforeImage->color[pixel][channel]) -
                                  static_cast<double>(afterImage->color[pixel][channel])));
        }
        const double bound = tight->rgbLInfBounds[pixel];
        sawCertifiedChange = sawCertifiedChange || bound > 0.0;
        if (actual > bound + 2.0e-6) {
            expect(false, "opacity-only reference difference exceeded delta certificate");
            return;
        }
    }
    expect(sawCertifiedChange, "non-identical opacity states need non-zero certified support");
}

void testOpacityDeltaCertificateBoundsOverlappingSplats() {
    aether::gaussian::GaussianAsset unchanged;
    unchanged.gaussians.push_back(primitive(0.18F, 3.35F, {0.1F, 0.7F, 0.3F}, 0.8F));

    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(primitive(-0.08F, 2.8F, {0.9F, 0.1F, 0.1F}, 2.8F));
    beforeChanged.gaussians.push_back(primitive(0.02F, 3.0F, {0.1F, 0.8F, 0.2F}, 1.4F));
    beforeChanged.gaussians.push_back(primitive(0.10F, 3.2F, {0.2F, 0.3F, 0.9F}, -0.2F));

    aether::gaussian::GaussianAsset afterChanged = beforeChanged;
    afterChanged.gaussians[0].opacityLogit = 2.6F;
    afterChanged.gaussians[1].opacityLogit = 1.55F;
    afterChanged.gaussians[2].opacityLogit = 0.05F;

    aether::gaussian::GaussianAsset beforeFull = unchanged;
    beforeFull.gaussians.insert(beforeFull.gaussians.end(), beforeChanged.gaussians.begin(),
                                beforeChanged.gaussians.end());
    aether::gaussian::GaussianAsset afterFull = unchanged;
    afterFull.gaussians.insert(afterFull.gaussians.end(), afterChanged.gaussians.begin(),
                               afterChanged.gaussians.end());

    const auto c = camera();
    const std::array<float, 3> background{0.05F, 0.12F, 0.2F};
    auto beforeImage = aether::gaussian::ReferenceRasterizer::render(beforeFull, c, background);
    auto afterImage = aether::gaussian::ReferenceRasterizer::render(afterFull, c, background);
    expect(beforeImage && afterImage, "overlapping opacity references must render");
    if (!beforeImage || !afterImage)
        return;

    const double cap = sceneColorCap(beforeChanged, afterChanged, unchanged);
    auto certificate = aether::world_gaussian::certifyGaussianOpacityOnlyImageRevision(
        beforeChanged, afterChanged, c, cap);
    expect(certificate.has_value(), "overlapping opacity-delta certificate must succeed");
    if (!certificate)
        return;

    bool sawActualChange = false;
    for (std::size_t pixel = 0; pixel < beforeImage->color.size(); ++pixel) {
        double actual{};
        for (std::size_t channel = 0; channel < 3; ++channel) {
            actual =
                std::max(actual,
                         std::abs(static_cast<double>(beforeImage->color[pixel][channel]) -
                                  static_cast<double>(afterImage->color[pixel][channel])));
        }
        sawActualChange = sawActualChange || actual > 0.0;
        if (actual > certificate->rgbLInfBounds[pixel] + 2.0e-6) {
            expect(false, "overlapping opacity difference exceeded delta certificate");
            return;
        }
    }
    expect(sawActualChange, "overlapping opacity test must exercise a visible change");
}

void testOpacityDeltaCertificateIsZeroForIdenticalStatesAndRejectsGeometryChange() {
    aether::gaussian::GaussianAsset beforeChanged;
    beforeChanged.gaussians.push_back(primitive(0.0F, 3.0F, {0.8F, 0.3F, 0.1F}, 1.5F));
    aether::gaussian::GaussianAsset afterChanged = beforeChanged;

    auto zero = aether::world_gaussian::certifyGaussianOpacityOnlyImageRevision(
        beforeChanged, afterChanged, camera(), 1.5);
    expect(zero.has_value(), "identical opacity-only states must certify");
    if (zero)
        expect(zero->maximumRgbLInfBound == 0.0,
               "identical opacity-only states must have zero delta bound");

    afterChanged.gaussians.front().position[0] += 0.01F;
    auto invalid = aether::world_gaussian::certifyGaussianOpacityOnlyImageRevision(
        beforeChanged, afterChanged, camera(), 1.5);
    expect(!invalid.has_value(), "opacity-only certificate must fail closed on geometry change");

    afterChanged = beforeChanged;
    afterChanged.sphericalHarmonicDegree = beforeChanged.sphericalHarmonicDegree + 1;
    auto degreeInvalid = aether::world_gaussian::certifyGaussianOpacityOnlyImageRevision(
        beforeChanged, afterChanged, camera(), 1.5);
    expect(!degreeInvalid.has_value(),
           "opacity-only certificate must fail closed on SH-degree change");
}

void testEmptyEditedSetsGiveZeroImageBound() {
    aether::gaussian::GaussianAsset empty;
    auto certificate =
        aether::world_gaussian::certifyGaussianImageRevision(empty, empty, camera(), 1.0);
    expect(certificate.has_value(), "empty edit certificate must succeed");
    if (!certificate)
        return;
    expect(certificate->maximumRgbLInfBound == 0.0, "empty edit must certify zero RGB change");
}

} // namespace

int main() noexcept {
    try {
        testProjectedCertificateBoundsExactReferenceDifference();
        testProjectedCertificateSupportsTranslatedCamera();
        testOpacityDeltaCertificateBoundsReferenceAndTightensSmallResidual();
        testOpacityDeltaCertificateBoundsOverlappingSplats();
        testOpacityDeltaCertificateIsZeroForIdenticalStatesAndRejectsGeometryChange();
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
