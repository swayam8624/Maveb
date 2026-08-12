#include <aether/reconstruction/TextureBaker.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>

namespace {

using aether::mesh::MeshPrimitive;
using aether::mesh::MeshVertex;
using aether::reconstruction::TextureBakeCamera;
using aether::reconstruction::TextureBakeConfig;
using aether::reconstruction::TextureBaker;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

MeshVertex vertex(float x, float y, float z) {
    MeshVertex result{};
    result.position = {x, y, z};
    result.normal = {0.0F, 0.0F, -1.0F};
    result.tangent = {1.0F, 0.0F, 0.0F, 1.0F};
    return result;
}

TextureBakeCamera camera(std::string name, float red) {
    TextureBakeCamera result;
    result.imageName = std::move(name);
    result.focalX = 48.0F;
    result.focalY = 48.0F;
    result.principalX = 32.0F;
    result.principalY = 32.0F;
    result.image.width = 64;
    result.image.height = 64;
    result.image.pixels.assign(std::size_t{64} * 64, simd_float3{red, 0.08F * red, 0.04F * red});
    return result;
}

TextureBakeConfig config() {
    TextureBakeConfig result;
    result.atlasSize = 64;
    result.gutterPixels = 2;
    result.visibilityWidth = 64;
    result.visibilityHeight = 64;
    return result;
}

void testExposureCompensatedPlane() {
    MeshPrimitive plane;
    plane.name = "metric-plane";
    plane.vertices = {vertex(-0.6F, -0.6F, 2.0F), vertex(0.6F, -0.6F, 2.0F),
                      vertex(0.6F, 0.6F, 2.0F), vertex(-0.6F, 0.6F, 2.0F)};
    plane.indices = {0, 1, 2, 0, 2, 3};
    auto bright = camera("bright.png", 0.8F);
    auto dark = camera("dark.png", 0.2F);
    dark.cameraToWorld.columns[3].x = 0.05F;

    const auto first = TextureBaker::bake(plane, {bright, dark}, config());
    const auto second = TextureBaker::bake(plane, {bright, dark}, config());
    expect(first.has_value(), "calibrated plane should bake");
    expect(second.has_value(), "repeated bake should succeed");
    if (!first || !second)
        return;
    expect(first->primitive.vertices.size() == 6, "atlas must split vertices at UV seams");
    expect(first->primitive.indices.size() == 6, "atlas must preserve both triangles");
    expect(first->report.coverage > 0.99F, "fully visible plane should have complete coverage");
    expect(first->report.exposureGains.size() == 2, "report must include every exposure gain");
    expect(first->report.exposureGains[1] > first->report.exposureGains[0],
           "darker input should receive a larger exposure gain");
    expect(first->coverageMask == second->coverageMask,
           "coverage and dilation must be deterministic");
    expect(first->atlasPixels.size() == second->atlasPixels.size(),
           "deterministic bake must preserve atlas size");
    bool identical = first->atlasPixels.size() == second->atlasPixels.size();
    for (std::size_t index = 0; identical && index < first->atlasPixels.size(); ++index)
        identical = simd_all(first->atlasPixels[index] == second->atlasPixels[index]);
    expect(identical, "identical inputs must produce byte-equivalent float atlases");
}

void testOcclusionAndInvalidInputs() {
    MeshPrimitive layers;
    layers.vertices = {vertex(-0.5F, -0.5F, 1.0F), vertex(0.5F, -0.5F, 1.0F),
                       vertex(0.0F, 0.5F, 1.0F),   vertex(-0.5F, -0.5F, 2.0F),
                       vertex(0.5F, -0.5F, 2.0F),  vertex(0.0F, 0.5F, 2.0F)};
    layers.indices = {0, 1, 2, 3, 4, 5};
    auto baked = TextureBaker::bake(layers, {camera("front.png", 0.5F)}, config());
    expect(baked.has_value(), "visible front layer should permit a partial bake");
    if (baked)
        expect(baked->report.unobservedTexels > 0 && baked->report.coverage < 0.75F,
               "depth oracle must reject the hidden layer");

    auto invalid = camera("invalid.png", 1.0F);
    invalid.focalX = 0.0F;
    expect(!TextureBaker::bake(layers, {invalid}, config()).has_value(),
           "invalid intrinsics must be rejected");
    auto unsafe = config();
    unsafe.atlasSize = 8;
    unsafe.gutterPixels = 3;
    expect(!TextureBaker::bake(layers, {camera("safe.png", 1.0F)}, unsafe).has_value(),
           "an atlas too small for guarded UV islands must be rejected");
}

} // namespace

int main() noexcept {
    try {
        testExposureCompensatedPlane();
        testOcclusionAndInvalidInputs();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }
    if (failures == 0)
        std::cout << "Texture baker tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
