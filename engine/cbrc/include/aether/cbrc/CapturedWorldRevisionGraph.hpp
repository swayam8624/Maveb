#pragma once

#include <aether/reconstruction/IncrementalSparseTsdfMesher.hpp>
#include <aether/revision/RevisionPlanner.hpp>
#include <aether/world/LocalityLedger.hpp>

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace aether::cbrc {

struct CapturedWorldCostModel final {
    std::string version;
    double observationMs{};
    double tsdfBlockMs{};
    double meshCellMs{};
    double meshPatchMs{};
    double texturePageMs{};
    double materialStateMs{};
    double gaussianInspectionMs{};
    double gaussianUpdateMs{};
    double gpuPublicationByteMs{};
    double temporalPixelMs{};
};

struct CapturedWorldRevisionInput final {
    std::size_t observationsInspected{};
    std::size_t fullObservations{};

    reconstruction::IncrementalSparseMesherWorkStatistics mesher;

    std::size_t dirtyTexturePages{};
    std::size_t fullTexturePages{};

    std::size_t materialStatesUpdated{};
    std::size_t fullMaterialStates{};

    std::size_t gaussiansInspected{};
    std::size_t gaussiansUpdated{};
    std::size_t fullGaussians{};

    std::uint64_t gpuPublicationBytes{};
    std::uint64_t fullGpuPublicationBytes{};

    std::uint64_t temporalPixelsInvalidated{};
    std::uint64_t fullTemporalPixels{};

    /// Conservative current-image L-infinity change from the Gaussian
    /// certificate, in the same absolute RGB units as epsilonRgbLInf.
    double gaussianCurrentRgbBound{};
    /// Stable temporal history weight. Used only when
    /// temporalValidationStable=true.
    double temporalHistoryWeight{0.9};
    bool temporalValidationStable{};

    double epsilonRgbLInf{};
};

struct CapturedWorldGraphBuild final {
    revision::RevisionGraph graph;
    std::vector<double> sourceBounds;
    std::vector<revision::RevisionNodeId> hardClosure;
    std::vector<revision::RevisionQoI> qois;

    revision::RevisionNodeId observation{};
    revision::RevisionNodeId tsdf{};
    revision::RevisionNodeId mesh{};
    revision::RevisionNodeId texture{};
    revision::RevisionNodeId material{};
    revision::RevisionNodeId gaussian{};
    revision::RevisionNodeId gpuPublication{};
    revision::RevisionNodeId currentImage{};
    revision::RevisionNodeId temporalHistory{};
    revision::RevisionNodeId resolvedImage{};
};

/// Creates the first production heterogeneous CBRC planning graph from work
/// already measured by MAVEB's reconstruction/rendering layers.
///
/// Structural dependencies are fail-closed:
/// - dirty TSDF implies exact TSDF + mesh repair;
/// - mesh changes imply texture-page repair when texture pages are dirty;
/// - changed Gaussians imply exact Gaussian + GPU publication repair;
/// - unstable temporal validation implies exact temporal-history invalidation.
///
/// Soft certification is used only for Gaussian current-image and stable
/// temporal blend propagation.
[[nodiscard]] Result<CapturedWorldGraphBuild>
buildCapturedWorldRevisionGraph(const CapturedWorldRevisionInput& input,
                                const CapturedWorldCostModel& costs);

/// Convert one validated heterogeneous LocalityLedger into the exact
/// planner-input counters consumed by buildCapturedWorldRevisionGraph.
/// Mesher counters are cross-checked against ledger mesh evidence so runtime
/// instrumentation and planner accounting cannot silently diverge.
[[nodiscard]] Result<CapturedWorldRevisionInput>
capturedWorldRevisionInputFromEvidence(
    const world::LocalityLedger& ledger,
    const reconstruction::IncrementalSparseMesherWorkStatistics& mesher,
    double gaussianCurrentRgbBound,
    double temporalHistoryWeight,
    bool temporalValidationStable,
    double epsilonRgbLInf);

[[nodiscard]] Result<revision::RevisionConeCertificate>
planCapturedWorldRevision(const CapturedWorldRevisionInput& input,
                          const CapturedWorldCostModel& costs);

} // namespace aether::cbrc
