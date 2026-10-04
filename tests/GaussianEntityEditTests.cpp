#include <aether/world_gaussian/GaussianEntityEdit.hpp>

#include <cmath>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <numbers>
#include <string>

namespace {

using aether::gaussian::Gaussian;
using aether::gaussian::GaussianAsset;
using aether::world::Bounds;
using aether::world::ChangeFlag;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::hasFlag;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world_gaussian::GaussianEntityEdit;
using aether::world_gaussian::GaussianEntityEditKind;
using aether::world_gaussian::GaussianEntityOwnership;
using aether::world_gaussian::GaussianOverlaySpatialIndex;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

bool close(float lhs, float rhs, float epsilon = 1.0e-4F) {
    return std::abs(lhs - rhs) <= epsilon;
}

EntityState entity(std::string name, float x) {
    EntityState result;
    result.name = std::move(name);
    result.semanticLabel = "fixture";
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.3F, -0.3F, -0.3F}, {x + 0.3F, 0.3F, 0.3F}};
    result.representation = RepresentationKind::gaussian;
    result.geometrySignature = 10;
    result.appearanceSignature = 20;
    return result;
}

Gaussian primitive(float x, float y, float z, float opacity = 0.0F) {
    Gaussian result;
    result.position = {x, y, z};
    result.logScale = {std::log(0.05F), std::log(0.06F), std::log(0.07F)};
    result.rotation = {1.0F, 0.0F, 0.0F, 0.0F};
    result.opacityLogit = opacity;
    return result;
}

struct Fixture final {
    PersistentWorldModel world;
    GaussianAsset asset;
    GaussianEntityOwnership ownership;
    GaussianOverlaySpatialIndex overlay;

    explicit Fixture(GaussianOverlaySpatialIndex index) : overlay(std::move(index)) {}
};

Fixture makeFixture() {
    PersistentWorldModel world;
    auto ingested = world.ingest(100, {entity("Edited", 0.0F), entity("Stable", 2.0F)});
    if (!ingested)
        throw std::runtime_error("fixture world ingest failed");

    GaussianAsset asset;
    asset.gaussians = {
        primitive(0.10F, 0.00F, 0.0F),
        primitive(0.00F, 0.20F, 0.0F),
        primitive(2.00F, 0.00F, 0.0F),
    };
    GaussianEntityOwnership ownership;
    ownership.owners = {EntityId{1}, EntityId{1}, EntityId{2}};
    auto overlay = GaussianOverlaySpatialIndex::build(asset, 0.5F);
    if (!overlay)
        throw std::runtime_error("fixture overlay build failed");

    Fixture result(std::move(*overlay));
    result.world = std::move(world);
    result.asset = std::move(asset);
    result.ownership = std::move(ownership);
    return result;
}

void testRotationChangesOwnedPositionsAndWorldDiff() {
    auto fixture = makeFixture();
    GaussianEntityEdit edit;
    edit.kind = GaussianEntityEditKind::rotation;
    edit.rotationAxis = {0.0F, 0.0F, 1.0F};
    edit.rotationRadians = std::numbers::pi_v<float> * 0.5F;

    auto result = aether::world_gaussian::editPersistentGaussianEntityIndexed(
        fixture.world, fixture.asset, fixture.ownership, fixture.overlay, EntityId{1}, edit, 200);
    expect(result.has_value(), "rotation transaction must commit");
    if (!result)
        return;
    expect(result->editedGaussians == 2, "rotation must edit exactly the owned primitive set");
    expect(result->overlayIndexValid, "rotation must preserve valid spatial overlay");
    expect(close(fixture.asset.gaussians[0].position[0], 0.0F) &&
               close(fixture.asset.gaussians[0].position[1], 0.10F),
           "rotation must rotate first owned Gaussian about persistent entity origin");
    expect(close(fixture.asset.gaussians[1].position[0], -0.20F) &&
               close(fixture.asset.gaussians[1].position[1], 0.0F),
           "rotation must rotate second owned Gaussian about persistent entity origin");
    expect(close(fixture.asset.gaussians[2].position[0], 2.0F),
           "rotation must leave another owner unchanged");
    expect(!result->worldEdit.diff.entities.empty() &&
               hasFlag(result->worldEdit.diff.entities.front().flags, ChangeFlag::rotated),
           "rotation must produce a rotated Reality Diff");
}

void testUniformScaleChangesCentersAndCovarianceScale() {
    auto fixture = makeFixture();
    const float beforeLogScale = fixture.asset.gaussians[0].logScale[0];
    GaussianEntityEdit edit;
    edit.kind = GaussianEntityEditKind::uniformScale;
    edit.uniformScale = 2.0F;

    auto result = aether::world_gaussian::editPersistentGaussianEntityIndexed(
        fixture.world, fixture.asset, fixture.ownership, fixture.overlay, EntityId{1}, edit, 200);
    expect(result.has_value(), "uniform-scale transaction must commit");
    if (!result)
        return;
    expect(close(fixture.asset.gaussians[0].position[0], 0.20F),
           "uniform scale must scale owned center about persistent entity origin");
    expect(close(fixture.asset.gaussians[1].position[1], 0.40F),
           "uniform scale must scale every owned center");
    expect(close(fixture.asset.gaussians[0].logScale[0], beforeLogScale + std::log(2.0F)),
           "uniform scale must update Gaussian covariance scale");
    expect(!result->worldEdit.diff.entities.empty() &&
               hasFlag(result->worldEdit.diff.entities.front().flags, ChangeFlag::scaled),
           "uniform scale must produce a scaled Reality Diff");
}

void testOpacityEditChangesAppearanceWithoutRelocation() {
    auto fixture = makeFixture();
    const auto beforeStats = fixture.overlay.statistics();
    GaussianEntityEdit edit;
    edit.kind = GaussianEntityEditKind::opacity;
    edit.opacityLogitDelta = 0.75F;

    auto result = aether::world_gaussian::editPersistentGaussianEntityIndexed(
        fixture.world, fixture.asset, fixture.ownership, fixture.overlay, EntityId{1}, edit, 200);
    expect(result.has_value(), "opacity transaction must commit");
    if (!result)
        return;
    expect(close(fixture.asset.gaussians[0].opacityLogit, 0.75F) &&
               close(fixture.asset.gaussians[1].opacityLogit, 0.75F),
           "opacity edit must alter every owned Gaussian");
    expect(close(fixture.asset.gaussians[2].opacityLogit, 0.0F),
           "opacity edit must leave stable owner appearance unchanged");
    expect(!result->worldEdit.diff.entities.empty() &&
               hasFlag(result->worldEdit.diff.entities.front().flags, ChangeFlag::appearance),
           "opacity edit must produce an appearance Reality Diff");
    const auto afterStats = fixture.overlay.statistics();
    expect(afterStats.deltaEntries == beforeStats.deltaEntries,
           "appearance-only edit must not create spatial overlay relocations");
}

void testInvalidScaleFailsBeforeWorldCommit() {
    auto fixture = makeFixture();
    GaussianEntityEdit edit;
    edit.kind = GaussianEntityEditKind::uniformScale;
    edit.uniformScale = 0.0F;
    const auto result = aether::world_gaussian::editPersistentGaussianEntityIndexed(
        fixture.world, fixture.asset, fixture.ownership, fixture.overlay, EntityId{1}, edit, 200);
    expect(!result.has_value(), "zero scale must fail closed");
    expect(fixture.world.timeline().size() == 1,
           "failed Gaussian edit must not append persistent world history");
    expect(close(fixture.asset.gaussians[0].position[0], 0.10F),
           "failed Gaussian edit must leave primitive state untouched");
}

} // namespace

int main() noexcept {
    try {
        testRotationChangesOwnedPositionsAndWorldDiff();
        testUniformScaleChangesCentersAndCovarianceScale();
        testOpacityEditChangesAppearanceWithoutRelocation();
        testInvalidScaleFailsBeforeWorldCommit();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Gaussian entity edit tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
