#pragma once

#include <aether/reconstruction/ReconstructionContracts.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace aether::reconstruction {

struct DenseTsdfConfig final {
    std::array<std::uint32_t, 3> dimensions{64, 64, 64};
    std::array<double, 3> originMetres{-0.5, -0.5, 0.0};
    double voxelSizeMetres{0.01};
    double truncationDistanceMetres{0.04};
    double minimumDepthMetres{0.05};
    double maximumDepthMetres{20.0};
    double maximumWeight{100.0};
};

struct TsdfVoxel final {
    float distance{1.0F};
    float weight{};
    std::array<float, 3> color{};
    std::uint32_t observations{};
};

struct DenseTsdfBoundsConfig final {
    std::uint32_t pixelStride{8};
    std::uint32_t maximumAxisVoxels{128};
    double minimumVoxelSizeMetres{0.01};
    double paddingMetres{0.08};
    double lowerQuantile{0.005};
    double upperQuantile{0.995};
};

struct DenseTsdfBoundsResult final {
    DenseTsdfConfig volume;
    std::array<double, 3> observedMinimumMetres{};
    std::array<double, 3> observedMaximumMetres{};
    std::size_t sampledPoints{};
};

/// Accumulates a bounded sample of calibrated metric depth in world space.
/// Input: image-aligned +Z-forward depth and a metric camera-to-world pose.
/// Output: a dense reference volume enclosing robust observed-surface quantiles.
/// Task: choose deterministic oracle bounds without trusting noisy depth extrema.
class DenseTsdfBoundsEstimator final {
public:
    static Result<DenseTsdfBoundsEstimator> create(DenseTsdfBoundsConfig config = {});

    Result<void> observe(const capture::CapturePacket& packet, const PoseEstimate& pose,
                         const DepthObservation& depth);
    Result<DenseTsdfBoundsResult> estimate() const;

private:
    explicit DenseTsdfBoundsEstimator(DenseTsdfBoundsConfig config);

    DenseTsdfBoundsConfig config_;
    std::array<std::vector<double>, 3> coordinates_;
};

/// Deterministic CPU correctness implementation. Camera coordinates use +Z forward.
class DenseTsdfVolume final : public IVolumeFusion, public IMeshExtractor {
public:
    static Result<DenseTsdfVolume> create(DenseTsdfConfig config);

    Result<void> integrate(const capture::CapturePacket& packet,
                           const PoseEstimate& pose,
                           const DepthObservation& depth) override;
    Result<mesh::MeshAsset> extractMesh() const override;

    [[nodiscard]] const DenseTsdfConfig& config() const noexcept { return config_; }
    [[nodiscard]] const std::vector<TsdfVoxel>& voxels() const noexcept { return voxels_; }
    [[nodiscard]] std::size_t integratedFrames() const noexcept { return integratedFrames_; }

private:
    explicit DenseTsdfVolume(DenseTsdfConfig config);
    [[nodiscard]] std::size_t index(std::uint32_t x, std::uint32_t y,
                                    std::uint32_t z) const noexcept;

    DenseTsdfConfig config_;
    std::vector<TsdfVoxel> voxels_;
    std::size_t integratedFrames_{};
};

} // namespace aether::reconstruction
