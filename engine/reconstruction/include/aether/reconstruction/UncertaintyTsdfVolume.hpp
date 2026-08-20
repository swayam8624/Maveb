#pragma once

#include <aether/reconstruction/DenseTsdfVolume.hpp>

#include <cstddef>
#include <cstdint>
#include <vector>

namespace aether::reconstruction {

/// U3 isolates only the fusion weight while preserving the dense CPU TSDF geometry path.
enum class TsdfFusionWeighting {
    uniform,
    naiveConfidence,
    calibratedInverseVariance,
};

/// Mirrors the frozen metric-uncertainty oracle. Defaults are generic; research runs must load the
/// fitted a/b/k terms explicitly rather than treating these defaults as evidence.
struct MetricUncertaintyFusionConfig final {
    double minimumSigmaMetres{0.001};
    double maximumSigmaMetres{0.25};
    double depthNoiseFloorMetres{0.002};
    double depthNoiseQuadraticMetresPerMetreSquared{0.0015};
    double sensorConfidencePenalty{2.0};
    double poseTranslationFloorMetres{0.001};
    double poseTranslationScaleMetres{0.02};
    double referenceSigmaMetres{0.01};
    double minimumPrecisionWeight{0.01};
    double maximumPrecisionWeight{1.0};
};

struct TsdfFusionWeight final {
    double sensorConfidence{1.0};
    double predictedSigmaMetres{};
    double precisionWeight{1.0};
    double sampleWeight{1.0};
};

struct UncertaintyTsdfConfig final {
    DenseTsdfConfig volume;
    TsdfFusionWeighting weighting{TsdfFusionWeighting::naiveConfidence};
    MetricUncertaintyFusionConfig uncertainty;
};

/// Deterministic scalar oracle used by the U3 implementation and its tests.
Result<TsdfFusionWeight> predictTsdfFusionWeight(double observedDepthMetres,
                                                 double sensorConfidence, const PoseEstimate& pose,
                                                 double focalLengthPixels,
                                                 TsdfFusionWeighting weighting,
                                                 const MetricUncertaintyFusionConfig& config);

/// Research-only dense CPU fusion path. It duplicates the reference projection/update loop so the
/// weighting intervention is isolated, then delegates mesh extraction to DenseTsdfVolume's existing
/// scalar-field oracle. The default naive-confidence mode is regression-tested against the original
/// DenseTsdfVolume voxel field.
class UncertaintyTsdfVolume final : public IVolumeFusion, public IMeshExtractor {
  public:
    static Result<UncertaintyTsdfVolume> create(UncertaintyTsdfConfig config);

    Result<void> integrate(const capture::CapturePacket& packet, const PoseEstimate& pose,
                           const DepthObservation& depth) override;
    Result<mesh::MeshAsset> extractMesh() const override;

    [[nodiscard]] const UncertaintyTsdfConfig& config() const noexcept {
        return config_;
    }
    [[nodiscard]] const std::vector<TsdfVoxel>& voxels() const noexcept {
        return voxels_;
    }
    [[nodiscard]] std::size_t integratedFrames() const noexcept {
        return integratedFrames_;
    }

  private:
    explicit UncertaintyTsdfVolume(UncertaintyTsdfConfig config);
    [[nodiscard]] std::size_t index(std::uint32_t x, std::uint32_t y,
                                    std::uint32_t z) const noexcept;

    UncertaintyTsdfConfig config_;
    std::vector<TsdfVoxel> voxels_;
    std::size_t integratedFrames_{};
};

} // namespace aether::reconstruction
