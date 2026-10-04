#pragma once

#include <aether/core/Error.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace aether::reconstruction {

/// One camera-to-world pose. Position is in the owning frame's units and orientation is (w,x,y,z).
struct AlignmentCameraPose final {
    std::array<double, 3> position{};
    std::array<double, 4> orientation{1.0, 0.0, 0.0, 0.0};
};

/// A visual identity observed by both the arbitrary-scale source rig and metric target rig.
struct CameraPoseCorrespondence final {
    std::string identity;
    AlignmentCameraPose source;
    AlignmentCameraPose target;
};

/// Metric target = scale * rotate(source) + translation. Rotation is stored as (w,x,y,z).
struct SimilarityTransform final {
    double scale{1.0};
    std::array<double, 4> orientation{1.0, 0.0, 0.0, 0.0};
    std::array<double, 3> translation{};

    /// Precondition: this transform and the supplied pose contain finite, normalized values.
    [[nodiscard]] std::array<double, 3>
    transformPosition(const std::array<double, 3>& source) const noexcept;
    [[nodiscard]] AlignmentCameraPose transformCamera(const AlignmentCameraPose& source) const;
};

struct SensorAlignmentConfig final {
    std::size_t maximumCorrespondences{1'000'000};
    std::size_t minimumInliers{6};
    std::size_t ransacIterations{1'024};
    std::size_t refinementIterations{8};
    std::uint64_t deterministicSeed{42};
    double positionInlierThresholdMetres{0.05};
    double orientationInlierThresholdDegrees{10.0};
    double huberDeltaMetres{0.02};
    double minimumInlierRatio{0.6};
    double maximumMedianPositionErrorMetres{0.025};
    double maximumP95PositionErrorMetres{0.075};
    double maximumMedianOrientationErrorDegrees{5.0};
    double maximumP95OrientationErrorDegrees{12.0};
    double minimumScale{1.0e-6};
    double maximumScale{1.0e6};
};

struct SensorAlignmentMetrics final {
    std::size_t correspondences{};
    std::size_t inliers{};
    double inlierRatio{};
    double positionRmseMetres{};
    double positionMedianMetres{};
    double positionP95Metres{};
    double positionMaximumMetres{};
    double orientationMedianDegrees{};
    double orientationP95Degrees{};
    double orientationMaximumDegrees{};
};

struct SensorAlignmentResult final {
    SimilarityTransform sourceToMetricTarget;
    SensorAlignmentMetrics metrics;
    std::vector<std::size_t> inlierIndices;
    std::vector<double> positionResidualsMetres;
    std::vector<double> orientationResidualsDegrees;
    bool accepted{};
    std::vector<std::string> issues;
};

/// Input: one-to-one COLMAP/source and metric/iPad camera-to-world correspondences plus bounded,
/// deterministic robust-fit thresholds.
/// Output: a source-to-metric Sim(3), per-pair residuals, deterministic inliers, and an explicit
/// quality-gate result. Quaternions are (w,x,y,z); camera axes must already share the same
/// convention. Task: reject correspondence outliers with seeded RANSAC, refine with Huber weights,
/// and measure metric position and orientation agreement without changing either input rig.
/// Failure: malformed/non-finite poses, duplicate identities, degenerate/near-collinear camera
/// motion, insufficient consensus, invalid thresholds, or an unbounded request returns an error.
[[nodiscard]] Result<SensorAlignmentResult>
alignCameraRigs(std::span<const CameraPoseCorrespondence> correspondences,
                const SensorAlignmentConfig& config = {});

} // namespace aether::reconstruction
