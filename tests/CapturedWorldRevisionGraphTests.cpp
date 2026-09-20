#include <aether/cbrc/CapturedWorldRevisionGraph.hpp>

#include <algorithm>
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

aether::cbrc::CapturedWorldCostModel costs() {
    return {
        .version = "fixture-cost-v1",
        .observationMs = 0.002,
        .tsdfBlockMs = 0.01,
        .meshCellMs = 0.001,
        .meshPatchMs = 0.01,
        .texturePageMs = 0.05,
        .materialStateMs = 0.01,
        .gaussianInspectionMs = 0.0001,
        .gaussianUpdateMs = 0.001,
        .gpuPublicationByteMs = 1.0e-6,
        .temporalPixelMs = 1.0e-5,
    };
}

aether::cbrc::CapturedWorldRevisionInput input() {
    aether::cbrc::CapturedWorldRevisionInput result;
    result.observationsInspected = 3;
    result.fullObservations = 100;
    result.mesher.dirtyBlocksInput = 2;
    result.mesher.snapshotBlocksScanned = 100;
    result.mesher.ownerPatchesRegenerated = 4;
    result.mesher.ownerCellsRegenerated = 1000;
    result.mesher.fullReferenceWorkAvailable = true;
    result.mesher.fullReferenceVoxelSamples = 125000;
    result.mesher.fullReferenceCells = 100000;
    result.dirtyTexturePages = 2;
    result.fullTexturePages = 100;
    result.materialStatesUpdated = 1;
    result.fullMaterialStates = 20;
    result.gaussiansInspected = 25;
    result.gaussiansUpdated = 5;
    result.fullGaussians = 1000;
    result.gpuPublicationBytes = 1280;
    result.fullGpuPublicationBytes = 256000;
    result.temporalPixelsInvalidated = 1000;
    result.fullTemporalPixels = 100000;
    result.gaussianCurrentRgbBound = 0.02;
    result.temporalHistoryWeight = 0.9;
    result.temporalValidationStable = true;
    result.epsilonRgbLInf = 0.03;
    return result;
}

bool contains(const std::vector<aether::revision::RevisionNodeId>& values,
              aether::revision::RevisionNodeId value) {
    return std::find(values.begin(), values.end(), value) != values.end();
}

void testStructuralHardClosureRegistersCrossLayerWork() {
    auto built = aether::cbrc::buildCapturedWorldRevisionGraph(input(), costs());
    expect(built.has_value(), "captured-world graph must build");
    if (!built)
        return;
    expect(contains(built->hardClosure, built->observation),
           "changed observations must be in exact hard closure");
    expect(contains(built->hardClosure, built->tsdf), "dirty TSDF must be in exact hard closure");
    expect(contains(built->hardClosure, built->mesh), "dirty TSDF must force exact mesh repair");
    expect(contains(built->hardClosure, built->texture),
           "dirty mesh-linked texture pages must be structural repair");
    expect(contains(built->hardClosure, built->material),
           "dirty material binding must be structural repair");
    expect(contains(built->hardClosure, built->gaussian), "Gaussian edit must be in hard closure");
    expect(contains(built->hardClosure, built->gpuPublication),
           "Gaussian edit must force exact GPU publication");
    expect(!contains(built->hardClosure, built->temporalHistory),
           "stable temporal validation may remain soft");
}

void testUnstableTemporalValidationPromotesHistoryToHard() {
    auto value = input();
    value.temporalValidationStable = false;
    auto built = aether::cbrc::buildCapturedWorldRevisionGraph(value, costs());
    expect(built.has_value(), "unstable temporal graph must still build");
    if (!built)
        return;
    expect(contains(built->hardClosure, built->temporalHistory),
           "unstable temporal validation must hard-invalidate history");
}

void testPlannerProducesCertifiedResult() {
    auto result = aether::cbrc::planCapturedWorldRevision(input(), costs());
    expect(result.has_value(), "captured-world planner must return result");
    if (!result)
        return;
    expect(result->passes, "captured-world result must satisfy RGB QoI");
    expect(result->stable, "captured-world result must be stable");
    expect(result->fullWork > result->work,
           "captured-world result must compare local work against independent full baseline");
}

void testIncrementalWorkCannotExceedFullBaseline() {
    auto value = input();
    value.gaussiansUpdated = value.fullGaussians + 1;
    auto result = aether::cbrc::buildCapturedWorldRevisionGraph(value, costs());
    expect(!result.has_value(),
           "captured-world adapter must reject impossible locality accounting");
}

void testMissingFrozenCostVersionFailsClosed() {
    auto model = costs();
    model.version.clear();
    auto result = aether::cbrc::buildCapturedWorldRevisionGraph(input(), model);
    expect(!result.has_value(), "unversioned cost model must fail closed");
}

} // namespace

int main() noexcept {
    try {
        testStructuralHardClosureRegistersCrossLayerWork();
        testUnstableTemporalValidationPromotesHistoryToHard();
        testPlannerProducesCertifiedResult();
        testIncrementalWorkCannotExceedFullBaseline();
        testMissingFrozenCostVersionFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Captured-world CBRC graph tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
