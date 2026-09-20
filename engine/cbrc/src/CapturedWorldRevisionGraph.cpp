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

[[nodiscard]] Result<double> checkedCost(double units, double coefficient,
                                         const char* label) {
    if (!finiteNonNegative(units) || !finiteNonNegative(coefficient))
        return fail(ErrorCode::invalidArgument,
                    "CBRC captured-world cost input must be finite and non-negative",
                    label);
    const double value = units * coefficient;
    if (!std::isfinite(value))
        return fail(ErrorCode::resourceExhausted,
                    "CBRC captured-world cost overflow", label);
    return value;
}

void appendUnique(std::vector<revision::RevisionNodeId>& values,
                  revision::RevisionNodeId value) {
    if (std::find(values.begin(), values.end(), value) == values.end())
        values.push_back(value);
}

} // namespace

Result<CapturedWorldGraphBuild>
buildCapturedWorldRevisionGraph(const CapturedWorldRevisionInput& input,
                                const CapturedWorldCostModel& costs) {
    if (costs.version.empty())
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC cost model requires a frozen version");
    if (!finiteNonNegative(input.gaussianCurrentRgbBound) ||
        !finiteNonNegative(input.epsilonRgbLInf) ||
        !std::isfinite(input.temporalHistoryWeight) ||
        input.temporalHistoryWeight < 0.0 ||
        input.temporalHistoryWeight > 1.0) {
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC certificate parameters are invalid");
    }
    if (input.gaussiansInspected > input.fullGaussians ||
        input.gaussiansUpdated > input.fullGaussians ||
        input.gpuPublicationBytes > input.fullGpuPublicationBytes ||
        input.temporalPixelsInvalidated > input.fullTemporalPixels ||
        input.dirtyTexturePages > input.fullTexturePages) {
        return fail(ErrorCode::invalidArgument,
                    "Captured-world CBRC incremental work exceeds full baseline");
    }

    auto tsdfCost = checkedCost(
        static_cast<double>(input.mesher.dirtyBlocksInput),
        costs.tsdfBlockMs, "tsdf");
    if (!tsdfCost)
        return std::unexpected(tsdfCost.error());

    auto meshCellCost = checkedCost(
        static_cast<double>(input.mesher.ownerCellsRegenerated),
        costs.meshCellMs, "mesh-cells");
    if (!meshCellCost)
        return std::unexpected(meshCellCost.error());
    auto meshPatchCost = checkedCost(
        static_cast<double>(input.mesher.ownerPatchesRegenerated),
        costs.meshPatchMs, "mesh-patches");
    if (!meshPatchCost)
        return std::unexpected(meshPatchCost.error());

    auto textureCost = checkedCost(
        static_cast<double>(input.dirtyTexturePages),
        costs.texturePageMs, "texture-pages");
    if (!textureCost)
        return std::unexpected(textureCost.error());

    auto gaussianInspectionCost = checkedCost(
        static_cast<double>(input.gaussiansInspected),
        costs.gaussianInspectionMs, "gaussian-inspection");
    if (!gaussianInspectionCost)
        return std::unexpected(gaussianInspectionCost.error());
    auto gaussianUpdateCost = checkedCost(
        static_cast<double>(input.gaussiansUpdated),
        costs.gaussianUpdateMs, "gaussian-update");
    if (!gaussianUpdateCost)
        return std::unexpected(gaussianUpdateCost.error());

    auto publicationCost = checkedCost(
        static_cast<double>(input.gpuPublicationBytes),
        costs.gpuPublicationByteMs, "gpu-publication");
    if (!publicationCost)
        return std::unexpected(publicationCost.error());

    auto temporalCost = checkedCost(
        static_cast<double>(input.temporalPixelsInvalidated),
        costs.temporalPixelMs, "temporal-history");
    if (!temporalCost)
        return std::unexpected(temporalCost.error());

    std::vector<revision::RevisionNode> nodes;
    nodes.reserve(8);
    const auto addNode = [&](std::string name, double work, double changeBound) {
        const auto id = static_cast<revision::RevisionNodeId>(nodes.size());
        nodes.push_back({std::move(name), work, changeBound});
        return id;
    };

    const auto tsdf = addNode("tsdf-block-repair", *tsdfCost, 0.0);
    const auto mesh = addNode("mesh-patch-repair",
                              *meshCellCost + *meshPatchCost, 0.0);
    const auto texture = addNode("texture-page-repair", *textureCost, 0.0);
    const auto gaussian = addNode(
        "gaussian-revision-repair",
        *gaussianInspectionCost + *gaussianUpdateCost,
        input.gaussianCurrentRgbBound);
    const auto gpuPublication =
        addNode("gpu-publication", *publicationCost, 0.0);
    const auto currentImage = addNode("current-image-qoi-state", 0.0, 0.0);
    const auto temporalHistory =
        addNode("temporal-history-repair", *temporalCost, 0.0);
    const auto resolvedImage = addNode("resolved-image-qoi", 0.0, 0.0);

    std::vector<revision::RevisionEdge> edges;
    edges.reserve(8);

    // Exact structural relations. The hardClosure below carries the forward
    // domain-specific invalidation; these edges retain predecessor consistency.
    edges.push_back(
        {tsdf, mesh, revision::RevisionEdgeClass::hard, 0.0,
         "tsdf-mesh-exact-closure-v0"});
    edges.push_back(
        {mesh, texture, revision::RevisionEdgeClass::hard, 0.0,
         "persistent-texture-pages-v1"});
    edges.push_back(
        {gaussian, gpuPublication, revision::RevisionEdgeClass::hard, 0.0,
         "gaussian-source-publication-v1"});

    // Certified soft output propagation.
    edges.push_back(
        {gaussian, currentImage, revision::RevisionEdgeClass::analytic, 1.0,
         "gaussian-image-transmittance-v1"});

    const double currentWeight =
        input.temporalValidationStable ? 1.0 - input.temporalHistoryWeight : 1.0;
    edges.push_back(
        {currentImage, resolvedImage, revision::RevisionEdgeClass::analytic,
         currentWeight, "temporal-current-blend-v1"});

    if (input.temporalValidationStable) {
        edges.push_back(
            {temporalHistory, resolvedImage,
             revision::RevisionEdgeClass::analytic,
             input.temporalHistoryWeight, "temporal-history-blend-v1"});
    } else {
        edges.push_back(
            {temporalHistory, resolvedImage, revision::RevisionEdgeClass::hard,
             0.0, "temporal-validation-discontinuity-v1"});
    }

    auto graph = revision::RevisionGraph::build(std::move(nodes), std::move(edges));
    if (!graph)
        return std::unexpected(graph.error());

    CapturedWorldGraphBuild result{
        .graph = std::move(*graph),
        .sourceBounds = std::vector<double>(8, 0.0),
        .hardClosure = {},
        .qois = {},
        .tsdf = tsdf,
        .mesh = mesh,
        .texture = texture,
        .gaussian = gaussian,
        .gpuPublication = gpuPublication,
        .currentImage = currentImage,
        .temporalHistory = temporalHistory,
        .resolvedImage = resolvedImage,
    };

    // Domain-specific exact forward invalidation.
    if (input.mesher.dirtyBlocksInput > 0) {
        appendUnique(result.hardClosure, tsdf);
        appendUnique(result.hardClosure, mesh);
        if (input.dirtyTexturePages > 0)
            appendUnique(result.hardClosure, texture);
    } else if (input.dirtyTexturePages > 0) {
        appendUnique(result.hardClosure, texture);
    }

    if (input.gaussiansUpdated > 0 || input.gaussiansInspected > 0) {
        appendUnique(result.hardClosure, gaussian);
        if (input.gpuPublicationBytes > 0)
            appendUnique(result.hardClosure, gpuPublication);
    }

    if (!input.temporalValidationStable &&
        input.temporalPixelsInvalidated > 0) {
        appendUnique(result.hardClosure, temporalHistory);
    }

    // If there is a direct current-image disturbance not already represented
    // by a repaired Gaussian node, it belongs in sourceBounds. The current v1
    // adapter has no such external image source, so the vector stays zero.
    result.qois.push_back(
        revision::RevisionQoI{
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
    return revision::greedyCertifiedRevisionCone(
        built->graph, built->sourceBounds, built->hardClosure, built->qois);
}

} // namespace aether::cbrc
