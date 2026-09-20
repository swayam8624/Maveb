#include <aether/cbrc/CapturedWorldRevisionGraph.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace aether::cbrc {
namespace {

[[nodiscard]] bool finiteNonNegative(double value) noexcept {
    return std::isfinite(value) && value >= 0.0;
}

[[nodiscard]] Result<std::size_t> checkedSize(std::uint64_t value,
                                               const char* label) {
    if (value > std::numeric_limits<std::size_t>::max())
        return fail(ErrorCode::resourceExhausted,
                    "CBRC locality counter exceeds size_t range", label);
    return static_cast<std::size_t>(value);
}

[[nodiscard]] Result<double> checkedCost(double units, double coefficient, const char* label) {
    if (!finiteNonNegative(units) || !finiteNonNegative(coefficient))
        return fail(ErrorCode::invalidArgument,
                    "CBRC captured-world cost input must be finite and non-negative", label);
    const double value = units * coefficient;
    if (!std::isfinite(value))
        return fail(ErrorCode::resourceExhausted, "CBRC captured-world cost overflow", label);
    return value;
}

void appendUnique(std::vector<revision::RevisionNodeId>& values, revision::RevisionNodeId value) {
    if (std::find(values.begin(), values.end(), value) == values.end())
        values.push_back(value);
}

} // namespace

Result<CapturedWorldRevisionInput> capturedWorldRevisionInputFromEvidence(
    const world::LocalityLedger& ledger,
    const reconstruction::IncrementalSparseMesherWorkStatistics& mesher,
    double gaussianCurrentRgbBound, double temporalHistoryWeight,
    bool temporalValidationStable, double epsilonRgbLInf) {
    if (auto validation = ledger.validateS1CoreCoverage(); !validation)
        return std::unexpected(validation.error());

    const auto observations =
        ledger.counter(world::LocalityDomain::observationsInspected);
    const auto meshCells =
        ledger.counter(world::LocalityDomain::meshCellsRegenerated);
    const auto meshPatches =
        ledger.counter(world::LocalityDomain::meshPatchesRegenerated);
    const auto texturePages =
        ledger.counter(world::LocalityDomain::texturePagesUpdated);
    const auto materials =
        ledger.counter(world::LocalityDomain::materialStatesUpdated);
    const auto gaussiansInspected =
        ledger.counter(world::LocalityDomain::gaussiansInspected);
    const auto gaussiansUpdated =
        ledger.counter(world::LocalityDomain::gaussiansUpdated);
    const auto publication =
        ledger.counter(world::LocalityDomain::gpuPublicationBytes);
    const auto temporal =
        ledger.counter(world::LocalityDomain::temporalPixelsInvalidated);

    if (meshCells.incremental != mesher.ownerCellsRegenerated ||
        meshCells.full != mesher.fullReferenceCells) {
        return fail(ErrorCode::invalidArgument,
                    "CBRC mesh-cell ledger disagrees with mesher statistics");
    }
    if (meshPatches.incremental != mesher.ownerPatchesRegenerated) {
        return fail(ErrorCode::invalidArgument,
                    "CBRC mesh-patch ledger disagrees with mesher statistics");
    }
    if (gaussiansInspected.full != gaussiansUpdated.full) {
        return fail(ErrorCode::invalidArgument,
                    "CBRC Gaussian full baselines disagree across inspection/update domains");
    }

    auto observationIncremental =
        checkedSize(observations.incremental, "observations.incremental");
    auto observationFull = checkedSize(observations.full, "observations.full");
    auto textureIncremental =
        checkedSize(texturePages.incremental, "texturePages.incremental");
    auto textureFull = checkedSize(texturePages.full, "texturePages.full");
    auto materialIncremental =
        checkedSize(materials.incremental, "materials.incremental");
    auto materialFull = checkedSize(materials.full, "materials.full");
    auto gaussianInspectionIncremental =
        checkedSize(gaussiansInspected.incremental, "gaussiansInspected.incremental");
    auto gaussianUpdateIncremental =
        checkedSize(gaussiansUpdated.incremental, "gaussiansUpdated.incremental");
    auto gaussianFull =
        checkedSize(gaussiansInspected.full, "gaussians.full");
    if (!observationIncremental || !observationFull || !textureIncremental ||
        !textureFull || !materialIncremental || !materialFull ||
        !gaussianInspectionIncremental || !gaussianUpdateIncremental ||
        !gaussianFull) {
        const Error* error = nullptr;
        if (!observationIncremental)
            error = &observationIncremental.error();
        else if (!observationFull)
            error = &observationFull.error();
        else if (!textureIncremental)
            error = &textureIncremental.error();
        else if (!textureFull)
            error = &textureFull.error();
        else if (!materialIncremental)
            error = &materialIncremental.error();
        else if (!materialFull)
            error = &materialFull.error();
        else if (!gaussianInspectionIncremental)
            error = &gaussianInspectionIncremental.error();
        else if (!gaussianUpdateIncremental)
            error = &gaussianUpdateIncremental.error();
        else
            error = &gaussianFull.error();
        return std::unexpected(*error);
    }

    return CapturedWorldRevisionInput{
        .observationsInspected = *observationIncremental,
        .fullObservations = *observationFull,
        .mesher = mesher,
        .dirtyTexturePages = *textureIncremental,
        .fullTexturePages = *textureFull,
        .materialStatesUpdated = *materialIncremental,
        .fullMaterialStates = *materialFull,
        .gaussiansInspected = *gaussianInspectionIncremental,
        .gaussiansUpdated = *gaussianUpdateIncremental,
        .fullGaussians = *gaussianFull,
        .gpuPublicationBytes = publication.incremental,
        .fullGpuPublicationBytes = publication.full,
        .temporalPixelsInvalidated = temporal.incremental,
        .fullTemporalPixels = temporal.full,
        .gaussianCurrentRgbBound = gaussianCurrentRgbBound,
        .temporalHistoryWeight = temporalHistoryWeight,
        .temporalValidationStable = temporalValidationStable,
        .epsilonRgbLInf = epsilonRgbLInf,
    };
}

Result<CapturedWorldGraphBuild>
buildCapturedWorldRevisionGraph(const CapturedWorldRevisionInput& input,
                                const CapturedWorldCostModel& costs) {
    if (costs.version.empty())
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC cost model requires a frozen version");
    if (!finiteNonNegative(input.gaussianCurrentRgbBound) ||
        !finiteNonNegative(input.epsilonRgbLInf) || !std::isfinite(input.temporalHistoryWeight) ||
        input.temporalHistoryWeight < 0.0 || input.temporalHistoryWeight > 1.0) {
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC certificate parameters are invalid");
    }
    if (input.mesher.dirtyBlocksInput > 0 && !input.mesher.fullReferenceWorkAvailable) {
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC mesh work requires a full-reference baseline");
    }
    if (input.observationsInspected > input.fullObservations ||
        input.dirtyTexturePages > input.fullTexturePages ||
        input.materialStatesUpdated > input.fullMaterialStates ||
        input.gaussiansInspected > input.fullGaussians ||
        input.gaussiansUpdated > input.fullGaussians ||
        input.gpuPublicationBytes > input.fullGpuPublicationBytes ||
        input.temporalPixelsInvalidated > input.fullTemporalPixels) {
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC incremental work exceeds full baseline");
    }

    auto observationCost = checkedCost(static_cast<double>(input.observationsInspected),
                                       costs.observationMs, "observations");
    if (!observationCost)
        return std::unexpected(observationCost.error());

    auto tsdfCost =
        checkedCost(static_cast<double>(input.mesher.dirtyBlocksInput), costs.tsdfBlockMs, "tsdf");
    if (!tsdfCost)
        return std::unexpected(tsdfCost.error());

    auto meshCellCost = checkedCost(static_cast<double>(input.mesher.ownerCellsRegenerated),
                                    costs.meshCellMs, "mesh-cells");
    if (!meshCellCost)
        return std::unexpected(meshCellCost.error());
    auto meshPatchCost = checkedCost(static_cast<double>(input.mesher.ownerPatchesRegenerated),
                                     costs.meshPatchMs, "mesh-patches");
    if (!meshPatchCost)
        return std::unexpected(meshPatchCost.error());

    auto textureCost = checkedCost(static_cast<double>(input.dirtyTexturePages),
                                   costs.texturePageMs, "texture-pages");
    if (!textureCost)
        return std::unexpected(textureCost.error());

    auto materialCost = checkedCost(static_cast<double>(input.materialStatesUpdated),
                                    costs.materialStateMs, "material-state");
    if (!materialCost)
        return std::unexpected(materialCost.error());

    auto gaussianInspectionCost = checkedCost(static_cast<double>(input.gaussiansInspected),
                                              costs.gaussianInspectionMs, "gaussian-inspection");
    if (!gaussianInspectionCost)
        return std::unexpected(gaussianInspectionCost.error());
    auto gaussianUpdateCost = checkedCost(static_cast<double>(input.gaussiansUpdated),
                                          costs.gaussianUpdateMs, "gaussian-update");
    if (!gaussianUpdateCost)
        return std::unexpected(gaussianUpdateCost.error());

    auto publicationCost = checkedCost(static_cast<double>(input.gpuPublicationBytes),
                                       costs.gpuPublicationByteMs, "gpu-publication");
    if (!publicationCost)
        return std::unexpected(publicationCost.error());

    auto temporalCost = checkedCost(static_cast<double>(input.temporalPixelsInvalidated),
                                    costs.temporalPixelMs, "temporal-history");
    if (!temporalCost)
        return std::unexpected(temporalCost.error());

    auto fullObservationCost = checkedCost(static_cast<double>(input.fullObservations),
                                           costs.observationMs, "full-observations");
    if (!fullObservationCost)
        return std::unexpected(fullObservationCost.error());
    auto fullTsdfCost = checkedCost(static_cast<double>(input.mesher.snapshotBlocksScanned),
                                    costs.tsdfBlockMs, "full-tsdf");
    if (!fullTsdfCost)
        return std::unexpected(fullTsdfCost.error());
    auto fullMeshCellCost = checkedCost(static_cast<double>(input.mesher.fullReferenceCells),
                                        costs.meshCellMs, "full-mesh-cells");
    if (!fullMeshCellCost)
        return std::unexpected(fullMeshCellCost.error());
    auto fullMeshPatchCost = checkedCost(static_cast<double>(input.mesher.snapshotBlocksScanned),
                                         costs.meshPatchMs, "full-mesh-patches");
    if (!fullMeshPatchCost)
        return std::unexpected(fullMeshPatchCost.error());
    auto fullTextureCost = checkedCost(static_cast<double>(input.fullTexturePages),
                                       costs.texturePageMs, "full-texture-pages");
    if (!fullTextureCost)
        return std::unexpected(fullTextureCost.error());
    auto fullMaterialCost = checkedCost(static_cast<double>(input.fullMaterialStates),
                                        costs.materialStateMs, "full-material-state");
    if (!fullMaterialCost)
        return std::unexpected(fullMaterialCost.error());
    auto fullGaussianInspectionCost =
        checkedCost(static_cast<double>(input.fullGaussians), costs.gaussianInspectionMs,
                    "full-gaussian-inspection");
    if (!fullGaussianInspectionCost)
        return std::unexpected(fullGaussianInspectionCost.error());
    auto fullGaussianUpdateCost = checkedCost(static_cast<double>(input.fullGaussians),
                                              costs.gaussianUpdateMs, "full-gaussian-update");
    if (!fullGaussianUpdateCost)
        return std::unexpected(fullGaussianUpdateCost.error());
    auto fullPublicationCost = checkedCost(static_cast<double>(input.fullGpuPublicationBytes),
                                           costs.gpuPublicationByteMs, "full-gpu-publication");
    if (!fullPublicationCost)
        return std::unexpected(fullPublicationCost.error());
    auto fullTemporalCost = checkedCost(static_cast<double>(input.fullTemporalPixels),
                                        costs.temporalPixelMs, "full-temporal-history");
    if (!fullTemporalCost)
        return std::unexpected(fullTemporalCost.error());

    const double fullWorkBaseline = *fullObservationCost + *fullTsdfCost + *fullMeshCellCost +
                                    *fullMeshPatchCost + *fullTextureCost + *fullMaterialCost +
                                    *fullGaussianInspectionCost + *fullGaussianUpdateCost +
                                    *fullPublicationCost + *fullTemporalCost;
    if (!std::isfinite(fullWorkBaseline))
        return fail(ErrorCode::resourceExhausted,
                    "Captured-world CBRC full-work baseline overflow");

    std::vector<revision::RevisionNode> nodes;
    nodes.reserve(10);
    const auto addNode = [&](std::string name, double work, double changeBound) {
        const auto id = static_cast<revision::RevisionNodeId>(nodes.size());
        nodes.push_back({std::move(name), work, changeBound});
        return id;
    };

    const auto observation = addNode("observation-repair", *observationCost, 0.0);
    const auto tsdf = addNode("tsdf-block-repair", *tsdfCost, 0.0);
    const auto mesh = addNode("mesh-patch-repair", *meshCellCost + *meshPatchCost, 0.0);
    const auto texture = addNode("texture-page-repair", *textureCost, 0.0);
    const auto material = addNode("material-state-repair", *materialCost, 0.0);
    const auto gaussian =
        addNode("gaussian-revision-repair", *gaussianInspectionCost + *gaussianUpdateCost,
                input.gaussianCurrentRgbBound);
    const auto gpuPublication = addNode("gpu-publication", *publicationCost, 0.0);
    const auto currentImage = addNode("current-image-qoi-state", 0.0, 0.0);
    const auto temporalHistory = addNode("temporal-history-repair", *temporalCost, 0.0);
    const auto resolvedImage = addNode("resolved-image-qoi", 0.0, 0.0);

    std::vector<revision::RevisionEdge> edges;
    edges.reserve(12);

    // Exact structural relations. The hardClosure below carries the forward
    // domain-specific invalidation; these edges retain predecessor consistency.
    edges.push_back({observation, tsdf, revision::RevisionEdgeClass::hard, 0.0,
                     "observation-tsdf-structural-v1"});
    edges.push_back(
        {tsdf, mesh, revision::RevisionEdgeClass::hard, 0.0, "tsdf-mesh-exact-closure-v0"});
    edges.push_back(
        {mesh, texture, revision::RevisionEdgeClass::hard, 0.0, "persistent-texture-pages-v1"});
    edges.push_back(
        {texture, material, revision::RevisionEdgeClass::hard, 0.0, "texture-material-binding-v1"});
    edges.push_back({gaussian, gpuPublication, revision::RevisionEdgeClass::hard, 0.0,
                     "gaussian-source-publication-v1"});

    // Certified soft output propagation.
    edges.push_back({gaussian, currentImage, revision::RevisionEdgeClass::analytic, 1.0,
                     "gaussian-image-transmittance-v1"});

    const double currentWeight =
        input.temporalValidationStable ? 1.0 - input.temporalHistoryWeight : 1.0;
    edges.push_back({currentImage, resolvedImage, revision::RevisionEdgeClass::analytic,
                     currentWeight, "temporal-current-blend-v1"});

    if (input.temporalValidationStable) {
        edges.push_back({temporalHistory, resolvedImage, revision::RevisionEdgeClass::analytic,
                         input.temporalHistoryWeight, "temporal-history-blend-v1"});
    } else {
        edges.push_back({temporalHistory, resolvedImage, revision::RevisionEdgeClass::hard, 0.0,
                         "temporal-validation-discontinuity-v1"});
    }

    auto graph =
        revision::RevisionGraph::build(std::move(nodes), std::move(edges), fullWorkBaseline);
    if (!graph)
        return std::unexpected(graph.error());

    CapturedWorldGraphBuild result{
        .graph = std::move(*graph),
        .sourceBounds = std::vector<double>(10, 0.0),
        .hardClosure = {},
        .qois = {},
        .observation = observation,
        .tsdf = tsdf,
        .mesh = mesh,
        .texture = texture,
        .material = material,
        .gaussian = gaussian,
        .gpuPublication = gpuPublication,
        .currentImage = currentImage,
        .temporalHistory = temporalHistory,
        .resolvedImage = resolvedImage,
    };

    // Domain-specific exact forward invalidation.
    if (input.observationsInspected > 0)
        appendUnique(result.hardClosure, observation);

    if (input.mesher.dirtyBlocksInput > 0) {
        appendUnique(result.hardClosure, tsdf);
        appendUnique(result.hardClosure, mesh);
        if (input.dirtyTexturePages > 0)
            appendUnique(result.hardClosure, texture);
        if (input.materialStatesUpdated > 0)
            appendUnique(result.hardClosure, material);
    } else if (input.dirtyTexturePages > 0) {
        appendUnique(result.hardClosure, texture);
        if (input.materialStatesUpdated > 0)
            appendUnique(result.hardClosure, material);
    } else if (input.materialStatesUpdated > 0) {
        appendUnique(result.hardClosure, material);
    }

    if (input.gaussiansUpdated > 0 || input.gaussiansInspected > 0) {
        appendUnique(result.hardClosure, gaussian);
        if (input.gpuPublicationBytes > 0)
            appendUnique(result.hardClosure, gpuPublication);
    }

    if (!input.temporalValidationStable && input.temporalPixelsInvalidated > 0) {
        appendUnique(result.hardClosure, temporalHistory);
    }

    // If there is a direct current-image disturbance not already represented
    // by a repaired Gaussian node, it belongs in sourceBounds. The current v1
    // adapter has no such external image source, so the vector stays zero.
    result.qois.push_back(revision::RevisionQoI{
        .name = "resolved-rgb-linf",
        .terms = {{resolvedImage, 1.0}},
        .epsilon = input.epsilonRgbLInf,
    });

    return result;
}

Result<revision::RevisionConeCertificate>
planCapturedWorldRevision(const CapturedWorldRevisionInput& input,
                          const CapturedWorldCostModel& costs) {
    auto built = buildCapturedWorldRevisionGraph(input, costs);
    if (!built)
        return std::unexpected(built.error());
    return revision::greedyCertifiedRevisionCone(built->graph, built->sourceBounds,
                                                 built->hardClosure, built->qois);
}

} // namespace aether::cbrc
