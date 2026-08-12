#include <aether/reconstruction/SensorAlignment.hpp>

#include <array>
#include <cmath>
#include <exception>
#include <iostream>
#include <numbers>
#include <string>
#include <vector>

namespace {

using aether::reconstruction::AlignmentCameraPose;
using aether::reconstruction::CameraPoseCorrespondence;
using aether::reconstruction::SensorAlignmentConfig;
using aether::reconstruction::SimilarityTransform;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        ++failures;
    }
}

std::array<double, 4> axisAngle(std::array<double, 3> axis, double degrees) {
    const double length = std::sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2]);
    const double halfAngle = degrees * std::numbers::pi / 360.0;
    const double sine = std::sin(halfAngle) / length;
    return {std::cos(halfAngle), axis[0] * sine, axis[1] * sine, axis[2] * sine};
}

std::array<double, 4> multiply(const std::array<double, 4>& left,
                               const std::array<double, 4>& right) {
    return {left[0] * right[0] - left[1] * right[1] - left[2] * right[2] - left[3] * right[3],
            left[0] * right[1] + left[1] * right[0] + left[2] * right[3] - left[3] * right[2],
            left[0] * right[2] - left[1] * right[3] + left[2] * right[0] + left[3] * right[1],
            left[0] * right[3] + left[1] * right[2] - left[2] * right[1] + left[3] * right[0]};
}

double quaternionAgreement(const std::array<double, 4>& left, const std::array<double, 4>& right) {
    return std::abs(left[0] * right[0] + left[1] * right[1] + left[2] * right[2] +
                    left[3] * right[3]);
}

std::vector<CameraPoseCorrespondence> fixture(const SimilarityTransform& truth) {
    constexpr std::array positions{
        std::array{-1.2, -0.5, 0.1}, std::array{-0.8, 0.4, 0.3}, std::array{-0.2, -0.9, 0.6},
        std::array{0.3, 0.8, -0.2},  std::array{0.9, -0.4, 0.9}, std::array{1.3, 0.5, 0.2},
        std::array{-0.7, 1.1, -0.6}, std::array{0.1, 1.4, 0.7},  std::array{0.8, 1.0, -0.8},
        std::array{1.5, -1.1, 0.4},  std::array{-1.4, 0.7, 1.0}, std::array{0.5, -1.3, -0.7},
    };
    std::vector<CameraPoseCorrespondence> result;
    result.reserve(positions.size());
    for (std::size_t index = 0; index < positions.size(); ++index) {
        AlignmentCameraPose source{positions[index],
                                   axisAngle({0.0, 1.0, 0.0}, static_cast<double>(index) * 7.0)};
        auto target = truth.transformCamera(source);
        target.position[0] += static_cast<double>(static_cast<int>(index % 3) - 1) * 0.0008;
        target.position[1] += static_cast<double>(static_cast<int>(index % 2)) * 0.0005;
        result.push_back(
            CameraPoseCorrespondence{"camera-" + std::to_string(index), source, target});
    }
    result[3].target.position = {4.0, -3.0, 2.0};
    result[3].target.orientation = axisAngle({1.0, 0.0, 0.0}, 120.0);
    result[9].target.position = {-5.0, 1.0, -4.0};
    result[9].target.orientation = axisAngle({0.0, 0.0, 1.0}, 150.0);
    return result;
}

void testRobustSimilarity() {
    const SimilarityTransform truth{2.35, axisAngle({0.2, -0.3, 0.4}, 37.0), {1.4, -0.7, 2.2}};
    const auto correspondences = fixture(truth);
    auto aligned = aether::reconstruction::alignCameraRigs(correspondences);
    expect(aligned.has_value(), "Robust sensor alignment accepts valid metric correspondences");
    if (!aligned)
        return;
    expect(aligned->accepted, "Low-error robust sensor alignment clears its quality gate");
    expect(aligned->metrics.inliers == 10 && aligned->metrics.correspondences == 12,
           "RANSAC rejects the two deterministic cross-device pose outliers");
    expect(std::abs(aligned->sourceToMetricTarget.scale - truth.scale) < 0.002,
           "Sensor alignment recovers metric scale");
    expect(quaternionAgreement(aligned->sourceToMetricTarget.orientation, truth.orientation) >
               0.999999,
           "Sensor alignment recovers world-frame rotation");
    for (std::size_t axis = 0; axis < 3; ++axis)
        expect(std::abs(aligned->sourceToMetricTarget.translation[axis] - truth.translation[axis]) <
                   0.002,
               "Sensor alignment recovers world-frame translation");
    expect(aligned->metrics.positionP95Metres < 0.003 &&
               aligned->metrics.orientationP95Degrees < 0.1,
           "Sensor alignment reports bounded held correspondence residuals");

    auto repeated = aether::reconstruction::alignCameraRigs(correspondences);
    expect(repeated.has_value() && repeated->inlierIndices == aligned->inlierIndices &&
               repeated->sourceToMetricTarget.scale == aligned->sourceToMetricTarget.scale &&
               repeated->sourceToMetricTarget.orientation ==
                   aligned->sourceToMetricTarget.orientation &&
               repeated->sourceToMetricTarget.translation ==
                   aligned->sourceToMetricTarget.translation,
           "Seeded robust sensor alignment is exactly deterministic");
}

void testQualityAndHostileInputs() {
    const SimilarityTransform truth{1.7, axisAngle({0.0, 0.0, 1.0}, 24.0), {0.4, 0.2, -0.1}};
    auto correspondences = fixture(truth);
    const auto mismatch = axisAngle({1.0, 0.0, 0.0}, 4.0);
    for (auto& correspondence : correspondences)
        if (correspondence.identity != "camera-3" && correspondence.identity != "camera-9")
            correspondence.target.orientation =
                multiply(mismatch, correspondence.target.orientation);
    SensorAlignmentConfig strict;
    strict.maximumMedianOrientationErrorDegrees = 1.0;
    strict.maximumP95OrientationErrorDegrees = 2.0;
    auto rejectedQuality = aether::reconstruction::alignCameraRigs(correspondences, strict);
    expect(rejectedQuality.has_value() && !rejectedQuality->accepted &&
               !rejectedQuality->issues.empty(),
           "A mathematically valid transform still fails an explicit orientation quality gate");

    std::vector<CameraPoseCorrespondence> collinear;
    for (std::size_t index = 0; index < 6; ++index) {
        AlignmentCameraPose pose{{static_cast<double>(index), 0.0, 0.0}, {1.0, 0.0, 0.0, 0.0}};
        collinear.push_back(CameraPoseCorrespondence{std::to_string(index), pose, pose});
    }
    expect(!aether::reconstruction::alignCameraRigs(collinear).has_value(),
           "Sensor alignment rejects a collinear camera trajectory");

    auto duplicates = fixture(truth);
    duplicates[1].identity = duplicates[0].identity;
    expect(!aether::reconstruction::alignCameraRigs(duplicates).has_value(),
           "Sensor alignment rejects duplicate visual identities");
    auto invalid = fixture(truth);
    invalid[0].source.orientation = {0.0, 0.0, 0.0, 0.0};
    expect(!aether::reconstruction::alignCameraRigs(invalid).has_value(),
           "Sensor alignment rejects a degenerate camera orientation");
    invalid = fixture(truth);
    invalid[0].source.orientation = {2.0, 0.0, 0.0, 0.0};
    expect(!aether::reconstruction::alignCameraRigs(invalid).has_value(),
           "Sensor alignment rejects a non-unit camera orientation");
}

int run() {
    testRobustSimilarity();
    testQualityAndHostileInputs();
    return failures == 0 ? 0 : 1;
}

} // namespace

int main() noexcept {
    try {
        return run();
    } catch (const std::exception& error) {
        std::cerr << "Unhandled sensor alignment test failure: " << error.what() << '\n';
    } catch (...) {
        std::cerr << "Unhandled sensor alignment test failure\n";
    }
    return 1;
}
