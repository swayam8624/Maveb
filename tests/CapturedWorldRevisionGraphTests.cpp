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

aether::world::LocalityLedger evidenceLedger(
    const aether::reconstruction::IncrementalSparseMesherWorkStatistics& mesher) {
    using aether::world::LocalityDomain;
    aether::world::LocalityLedger ledger;
    const auto set = [&](LocalityDomain domain, std::uint64_t incremental,
                         std::uint64_t full) {
        expect(ledger.set(domain, incremental, full).has_value(),
               "fixture locality domain must accept valid evidence");
    };
    set(LocalityDomain::observationsInspected, 3, 100);
    set(LocalityDomain::tsdfBlocksRead, mesher.snapshotBlocksScanned,
        mesher.snapshotBlocksScanned);
    set(LocalityDomain::tsdfBlocksWritten, mesher.dirtyBlocksInput,
        mesher.snapshotBlocksScanned);
    set(LocalityDomain::meshCellsRegenerated, mesher.ownerCellsRegenerated,
        mesher.fullReferenceCells);
    set(LocalityDomain::meshPatchesRegenerated, mesher.ownerPatchesRegenerated,
        mesher.snapshotBlocksScanned);
    set(LocalityDomain::gaussiansInspected, 25, 1000);
    set(LocalityDomain::gaussiansUpdated, 5, 1000);
    set(LocalityDomain::texturePagesUpdated, 2, 100);
    set(LocalityDomain::textureSlotsConsidered, 8, 400);
    set(LocalityDomain::textureTexelsWritten, 1024, 100000);
    set(LocalityDomain::materialStatesUpdated, 1, 20);
    set(LocalityDomain::gpuPublicationBytes, 1280, 256000);
    set(LocalityDomain::temporalPixelsInvalidated, 1000, 100000);
    return ledger;
}

void testValidatedLedgerBuildsPlannerInput() {
    const auto expected = input();
    auto ledger = evidenceLedger(expected.mesher);
    auto adapted = aether::cbrc::capturedWorldRevisionInputFromEvidence(
        ledger, expected.mesher, expected.gaussianCurrentRgbBound,
        expected.temporalHistoryWeight, expected.temporalValidationStable,
        expected.epsilonRgbLInf);
    expect(adapted.has_value(), "validated locality ledger must adapt to CBRC input");
    if (!adapted)
        return;
    expect(adapted->observationsInspected == expected.observationsInspected &&
               adapted->dirtyTexturePages == expected.dirtyTexturePages &&
               adapted->materialStatesUpdated == expected.materialStatesUpdated &&
               adapted->gaussiansUpdated == expected.gaussiansUpdated &&
               adapted->gpuPublicationBytes == expected.gpuPublicationBytes &&
               adapted->temporalPixelsInvalidated == expected.temporalPixelsInvalidated,
           "ledger adapter must preserve heterogeneous incremental counters");

    auto planned = aether::cbrc::planCapturedWorldRevision(*adapted, costs());
    expect(planned.has_value() && planned->passes,
           "ledger-derived captured-world input must be directly plannable");
}

void testLedgerMesherDisagreementFailsClosed() {
    const auto expected = input();
    auto ledger = evidenceLedger(expected.mesher);
    auto mismatched = expected.mesher;
    ++mismatched.ownerCellsRegenerated;
    auto adapted = aether::cbrc::capturedWorldRevisionInputFromEvidence(
        ledger, mismatched, expected.gaussianCurrentRgbBound,
        expected.temporalHistoryWeight, expected.temporalValidationStable,
        expected.epsilonRgbLInf);
    expect(!adapted.has_value(),
           "ledger/mesher counter disagreement must not reach planner");
}

void testGaussianFullBaselineDisagreementFailsClosed() {
    using aether::world::LocalityDomain;
    const auto expected = input();
    auto ledger = evidenceLedger(expected.mesher);
    expect(ledger.set(LocalityDomain::gaussiansUpdated, 5, 999).has_value(),
           "fixture must permit internally inconsistent Gaussian baselines");
    auto adapted = aether::cbrc::capturedWorldRevisionInputFromEvidence(
        ledger, expected.mesher, expected.gaussianCurrentRgbBound,
        expected.temporalHistoryWeight, expected.temporalValidationStable,
        expected.epsilonRgbLInf);
    expect(!adapted.has_value(),
           "Gaussian full-baseline disagreement must fail closed");
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
        testValidatedLedgerBuildsPlannerInput();
        testLedgerMesherDisagreementFailsClosed();
        testGaussianFullBaselineDisagreementFailsClosed();
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
