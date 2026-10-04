#include <aether/reconstruction/SensorAlignment.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numeric>
#include <unordered_set>

namespace aether::reconstruction {
namespace {

using Vector3 = std::array<double, 3>;
using Quaternion = std::array<double, 4>;
using Matrix4 = std::array<std::array<double, 4>, 4>;

constexpr double radiansToDegrees = 57.2957795130823208768;

bool finite(double value) {
    return std::isfinite(value);
}

bool finite(const Vector3& value) {
    return std::ranges::all_of(value, [](double component) { return finite(component); });
}

bool finite(const Quaternion& value) {
    return std::ranges::all_of(value, [](double component) { return finite(component); });
}

Vector3 add(const Vector3& left, const Vector3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vector3 subtract(const Vector3& left, const Vector3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vector3 multiply(const Vector3& value, double scalar) {
    return {value[0] * scalar, value[1] * scalar, value[2] * scalar};
}

double dot(const Vector3& left, const Vector3& right) {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

Vector3 cross(const Vector3& left, const Vector3& right) {
    return {left[1] * right[2] - left[2] * right[1], left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0]};
}

double squaredLength(const Vector3& value) {
    return dot(value, value);
}

double length(const Vector3& value) {
    return std::sqrt(squaredLength(value));
}

Result<Quaternion> normalized(Quaternion value) {
    const double magnitude = std::sqrt(value[0] * value[0] + value[1] * value[1] +
                                       value[2] * value[2] + value[3] * value[3]);
    if (!finite(value) || !finite(magnitude) || magnitude <= 1.0e-12)
        return fail(ErrorCode::corruptData, "Camera orientation quaternion is invalid");
    for (auto& component : value)
        component /= magnitude;
    if (value[0] < 0.0)
        for (auto& component : value)
            component = -component;
    return value;
}

bool unitQuaternion(const Quaternion& value) {
    if (!finite(value))
        return false;
    const double squaredMagnitude =
        value[0] * value[0] + value[1] * value[1] + value[2] * value[2] + value[3] * value[3];
    return finite(squaredMagnitude) && std::abs(squaredMagnitude - 1.0) <= 1.0e-6;
}

Quaternion multiply(const Quaternion& left, const Quaternion& right) {
    return {left[0] * right[0] - left[1] * right[1] - left[2] * right[2] - left[3] * right[3],
            left[0] * right[1] + left[1] * right[0] + left[2] * right[3] - left[3] * right[2],
            left[0] * right[2] - left[1] * right[3] + left[2] * right[0] + left[3] * right[1],
            left[0] * right[3] + left[1] * right[2] - left[2] * right[1] + left[3] * right[0]};
}

Vector3 rotate(const Quaternion& quaternion, const Vector3& value) {
    const Vector3 imaginary{quaternion[1], quaternion[2], quaternion[3]};
    const auto twiceCross = multiply(cross(imaginary, value), 2.0);
    return add(value, add(multiply(twiceCross, quaternion[0]), cross(imaginary, twiceCross)));
}

double orientationErrorDegrees(const Quaternion& predicted, const Quaternion& target) {
    const double product = std::abs(predicted[0] * target[0] + predicted[1] * target[1] +
                                    predicted[2] * target[2] + predicted[3] * target[3]);
    return 2.0 * std::acos(std::clamp(product, 0.0, 1.0)) * radiansToDegrees;
}

double percentile(std::vector<double> values, double fraction) {
    std::ranges::sort(values);
    if (values.size() == 1)
        return values.front();
    const double location = fraction * static_cast<double>(values.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(location));
    const auto upper = static_cast<std::size_t>(std::ceil(location));
    const double weight = location - static_cast<double>(lower);
    return values[lower] * (1.0 - weight) + values[upper] * weight;
}

class DeterministicGenerator final {
  public:
    explicit DeterministicGenerator(std::uint64_t seed) : state_(seed == 0 ? 1 : seed) {}

    std::size_t index(std::size_t bound) {
        state_ ^= state_ >> 12U;
        state_ ^= state_ << 25U;
        state_ ^= state_ >> 27U;
        const std::uint64_t value = state_ * 0x2545f4914f6cdd1dULL;
        return static_cast<std::size_t>(value % bound);
    }

  private:
    std::uint64_t state_;
};

Result<Quaternion> largestEigenQuaternion(Matrix4 matrix) {
    Matrix4 eigenvectors{};
    for (std::size_t index = 0; index < 4; ++index)
        eigenvectors[index][index] = 1.0;
    for (std::size_t sweep = 0; sweep < 64; ++sweep) {
        std::size_t first{};
        std::size_t second{1};
        double largest = std::abs(matrix[first][second]);
        for (std::size_t row = 0; row < 4; ++row)
            for (std::size_t column = row + 1; column < 4; ++column)
                if (std::abs(matrix[row][column]) > largest) {
                    largest = std::abs(matrix[row][column]);
                    first = row;
                    second = column;
                }
        if (largest <= 1.0e-15)
            break;
        const double angle = 0.5 * std::atan2(2.0 * matrix[first][second],
                                              matrix[second][second] - matrix[first][first]);
        const double cosine = std::cos(angle);
        const double sine = std::sin(angle);
        for (std::size_t index = 0; index < 4; ++index) {
            if (index == first || index == second)
                continue;
            const double left = matrix[index][first];
            const double right = matrix[index][second];
            matrix[index][first] = matrix[first][index] = cosine * left - sine * right;
            matrix[index][second] = matrix[second][index] = sine * left + cosine * right;
        }
        const double diagonalFirst = matrix[first][first];
        const double diagonalSecond = matrix[second][second];
        const double offDiagonal = matrix[first][second];
        matrix[first][first] = cosine * cosine * diagonalFirst - 2.0 * sine * cosine * offDiagonal +
                               sine * sine * diagonalSecond;
        matrix[second][second] = sine * sine * diagonalFirst + 2.0 * sine * cosine * offDiagonal +
                                 cosine * cosine * diagonalSecond;
        matrix[first][second] = matrix[second][first] = 0.0;
        for (std::size_t row = 0; row < 4; ++row) {
            const double left = eigenvectors[row][first];
            const double right = eigenvectors[row][second];
            eigenvectors[row][first] = cosine * left - sine * right;
            eigenvectors[row][second] = sine * left + cosine * right;
        }
    }
    std::size_t largestIndex{};
    for (std::size_t index = 1; index < 4; ++index)
        if (matrix[index][index] > matrix[largestIndex][largestIndex])
            largestIndex = index;
    return normalized({eigenvectors[0][largestIndex], eigenvectors[1][largestIndex],
                       eigenvectors[2][largestIndex], eigenvectors[3][largestIndex]});
}

Result<SimilarityTransform> fitSimilarity(std::span<const CameraPoseCorrespondence> correspondences,
                                          std::span<const std::size_t> indices,
                                          std::span<const double> weights,
                                          const SensorAlignmentConfig& config) {
    if (indices.size() < 3 || (!weights.empty() && weights.size() != indices.size()))
        return fail(ErrorCode::invalidArgument, "Similarity fit requires at least three pairs");
    Vector3 sourceMean{};
    Vector3 targetMean{};
    double totalWeight{};
    for (std::size_t local = 0; local < indices.size(); ++local) {
        const double weight = weights.empty() ? 1.0 : weights[local];
        if (!finite(weight) || weight <= 0.0)
            return fail(ErrorCode::invalidArgument, "Similarity fit weight is invalid");
        sourceMean =
            add(sourceMean, multiply(correspondences[indices[local]].source.position, weight));
        targetMean =
            add(targetMean, multiply(correspondences[indices[local]].target.position, weight));
        totalWeight += weight;
    }
    sourceMean = multiply(sourceMean, 1.0 / totalWeight);
    targetMean = multiply(targetMean, 1.0 / totalWeight);

    std::array<std::array<double, 3>, 3> covariance{};
    double sourceVariance{};
    double targetVariance{};
    double maximumCrossSquared{};
    std::vector<Vector3> centeredSource;
    centeredSource.reserve(indices.size());
    for (std::size_t local = 0; local < indices.size(); ++local) {
        const double weight = weights.empty() ? 1.0 : weights[local];
        const auto source = subtract(correspondences[indices[local]].source.position, sourceMean);
        const auto target = subtract(correspondences[indices[local]].target.position, targetMean);
        centeredSource.push_back(source);
        sourceVariance += weight * squaredLength(source);
        targetVariance += weight * squaredLength(target);
        for (std::size_t row = 0; row < 3; ++row)
            for (std::size_t column = 0; column < 3; ++column)
                covariance[row][column] += weight * source[row] * target[column];
    }
    for (std::size_t left = 0; left < centeredSource.size(); ++left)
        for (std::size_t right = left + 1; right < centeredSource.size(); ++right)
            maximumCrossSquared =
                std::max(maximumCrossSquared,
                         squaredLength(cross(centeredSource[left], centeredSource[right])));
    if (!finite(sourceVariance) || !finite(targetVariance) || sourceVariance <= 1.0e-18 ||
        targetVariance <= 1.0e-18 ||
        maximumCrossSquared <= sourceVariance * sourceVariance * 1.0e-12)
        return fail(ErrorCode::invalidArgument,
                    "Camera centers are degenerate or insufficiently non-collinear");

    const double sxx = covariance[0][0];
    const double sxy = covariance[0][1];
    const double sxz = covariance[0][2];
    const double syx = covariance[1][0];
    const double syy = covariance[1][1];
    const double syz = covariance[1][2];
    const double szx = covariance[2][0];
    const double szy = covariance[2][1];
    const double szz = covariance[2][2];
    Matrix4 horn{{{{sxx + syy + szz, syz - szy, szx - sxz, sxy - syx}},
                  {{syz - szy, sxx - syy - szz, sxy + syx, szx + sxz}},
                  {{szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy}},
                  {{sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz}}}};
    auto orientation = largestEigenQuaternion(horn);
    if (!orientation)
        return std::unexpected(orientation.error());
    double scaleNumerator{};
    for (std::size_t local = 0; local < indices.size(); ++local) {
        const double weight = weights.empty() ? 1.0 : weights[local];
        const auto source = subtract(correspondences[indices[local]].source.position, sourceMean);
        const auto target = subtract(correspondences[indices[local]].target.position, targetMean);
        scaleNumerator += weight * dot(target, rotate(*orientation, source));
    }
    const double scale = scaleNumerator / sourceVariance;
    if (!finite(scale) || scale < config.minimumScale || scale > config.maximumScale)
        return fail(ErrorCode::invalidArgument, "Recovered similarity scale is invalid");
    const auto translation =
        subtract(targetMean, multiply(rotate(*orientation, sourceMean), scale));
    if (!finite(translation))
        return fail(ErrorCode::internal, "Recovered similarity translation is invalid");
    return SimilarityTransform{scale, *orientation, translation};
}

struct ResidualSet final {
    std::vector<double> positions;
    std::vector<double> orientations;
    std::vector<std::size_t> inliers;
};

ResidualSet residuals(const SimilarityTransform& transform,
                      std::span<const CameraPoseCorrespondence> correspondences,
                      const SensorAlignmentConfig& config) {
    ResidualSet result;
    result.positions.reserve(correspondences.size());
    result.orientations.reserve(correspondences.size());
    result.inliers.reserve(correspondences.size());
    for (std::size_t index = 0; index < correspondences.size(); ++index) {
        const auto transformed = transform.transformCamera(correspondences[index].source);
        const double position =
            length(subtract(transformed.position, correspondences[index].target.position));
        const double orientation = orientationErrorDegrees(
            transformed.orientation, correspondences[index].target.orientation);
        result.positions.push_back(position);
        result.orientations.push_back(orientation);
        if (position <= config.positionInlierThresholdMetres &&
            orientation <= config.orientationInlierThresholdDegrees)
            result.inliers.push_back(index);
    }
    return result;
}

bool betterConsensus(const ResidualSet& candidate, const ResidualSet& current) {
    if (candidate.inliers.size() != current.inliers.size())
        return candidate.inliers.size() > current.inliers.size();
    double candidateError{};
    for (const auto index : candidate.inliers)
        candidateError += candidate.positions[index];
    double currentError{};
    for (const auto index : current.inliers)
        currentError += current.positions[index];
    return candidateError < currentError;
}

Result<void> validateConfig(const SensorAlignmentConfig& config) {
    if (config.maximumCorrespondences < 3 || config.minimumInliers < 3 ||
        config.minimumInliers > config.maximumCorrespondences || config.ransacIterations == 0 ||
        config.refinementIterations == 0 || !finite(config.positionInlierThresholdMetres) ||
        config.positionInlierThresholdMetres <= 0.0 ||
        !finite(config.orientationInlierThresholdDegrees) ||
        config.orientationInlierThresholdDegrees <= 0.0 ||
        config.orientationInlierThresholdDegrees > 180.0 || !finite(config.huberDeltaMetres) ||
        config.huberDeltaMetres <= 0.0 || !finite(config.minimumInlierRatio) ||
        config.minimumInlierRatio <= 0.0 || config.minimumInlierRatio > 1.0 ||
        !finite(config.maximumMedianPositionErrorMetres) ||
        config.maximumMedianPositionErrorMetres <= 0.0 ||
        !finite(config.maximumP95PositionErrorMetres) ||
        config.maximumP95PositionErrorMetres < config.maximumMedianPositionErrorMetres ||
        !finite(config.maximumMedianOrientationErrorDegrees) ||
        config.maximumMedianOrientationErrorDegrees <= 0.0 ||
        !finite(config.maximumP95OrientationErrorDegrees) ||
        config.maximumP95OrientationErrorDegrees < config.maximumMedianOrientationErrorDegrees ||
        !finite(config.minimumScale) || !finite(config.maximumScale) ||
        config.minimumScale <= 0.0 || config.maximumScale <= config.minimumScale)
        return fail(ErrorCode::invalidArgument, "Sensor alignment configuration is invalid");
    return {};
}

} // namespace

std::array<double, 3>
SimilarityTransform::transformPosition(const std::array<double, 3>& source) const noexcept {
    return add(multiply(rotate(orientation, source), scale), translation);
}

AlignmentCameraPose SimilarityTransform::transformCamera(const AlignmentCameraPose& source) const {
    return AlignmentCameraPose{transformPosition(source.position),
                               multiply(orientation, source.orientation)};
}

Result<SensorAlignmentResult>
alignCameraRigs(std::span<const CameraPoseCorrespondence> correspondences,
                const SensorAlignmentConfig& config) {
    if (auto validated = validateConfig(config); !validated)
        return std::unexpected(validated.error());
    if (correspondences.size() < config.minimumInliers ||
        correspondences.size() > config.maximumCorrespondences)
        return fail(ErrorCode::invalidArgument,
                    "Sensor alignment correspondence count is outside configured bounds");
    std::unordered_set<std::string> identities;
    for (const auto& correspondence : correspondences) {
        if (correspondence.identity.empty() || !identities.insert(correspondence.identity).second)
            return fail(ErrorCode::corruptData,
                        "Sensor alignment identities must be non-empty and unique");
        if (!finite(correspondence.source.position) || !finite(correspondence.target.position))
            return fail(ErrorCode::corruptData, "Sensor alignment position is non-finite",
                        correspondence.identity);
        if (!unitQuaternion(correspondence.source.orientation) ||
            !unitQuaternion(correspondence.target.orientation))
            return fail(ErrorCode::corruptData, "Sensor alignment orientation is invalid",
                        correspondence.identity);
    }

    DeterministicGenerator generator(config.deterministicSeed);
    ResidualSet best;
    SimilarityTransform bestTransform;
    for (std::size_t iteration = 0; iteration < config.ransacIterations; ++iteration) {
        std::array<std::size_t, 3> sample{};
        sample[0] = generator.index(correspondences.size());
        do
            sample[1] = generator.index(correspondences.size());
        while (sample[1] == sample[0]);
        do
            sample[2] = generator.index(correspondences.size());
        while (sample[2] == sample[0] || sample[2] == sample[1]);
        auto candidate = fitSimilarity(correspondences, sample, {}, config);
        if (!candidate)
            continue;
        auto candidateResiduals = residuals(*candidate, correspondences, config);
        if (betterConsensus(candidateResiduals, best)) {
            best = std::move(candidateResiduals);
            bestTransform = *candidate;
        }
    }
    if (best.inliers.size() < config.minimumInliers)
        return fail(ErrorCode::corruptData,
                    "Sensor alignment could not find the required robust camera consensus");

    for (std::size_t iteration = 0; iteration < config.refinementIterations; ++iteration) {
        std::vector<double> weights;
        weights.reserve(best.inliers.size());
        for (const auto index : best.inliers) {
            const double residual = best.positions[index];
            weights.push_back(
                residual <= config.huberDeltaMetres ? 1.0 : config.huberDeltaMetres / residual);
        }
        auto refined = fitSimilarity(correspondences, best.inliers, weights, config);
        if (!refined)
            return std::unexpected(refined.error());
        bestTransform = *refined;
        auto refinedResiduals = residuals(bestTransform, correspondences, config);
        if (refinedResiduals.inliers.size() < config.minimumInliers)
            return fail(ErrorCode::corruptData,
                        "Sensor alignment refinement lost the required camera consensus");
        const bool stable = refinedResiduals.inliers == best.inliers;
        best = std::move(refinedResiduals);
        if (stable)
            break;
    }

    std::vector<double> inlierPositions;
    std::vector<double> inlierOrientations;
    inlierPositions.reserve(best.inliers.size());
    inlierOrientations.reserve(best.inliers.size());
    double squaredPositionError{};
    for (const auto index : best.inliers) {
        inlierPositions.push_back(best.positions[index]);
        inlierOrientations.push_back(best.orientations[index]);
        squaredPositionError += best.positions[index] * best.positions[index];
    }
    SensorAlignmentResult result;
    result.sourceToMetricTarget = bestTransform;
    result.inlierIndices = best.inliers;
    result.positionResidualsMetres = std::move(best.positions);
    result.orientationResidualsDegrees = std::move(best.orientations);
    result.metrics.correspondences = correspondences.size();
    result.metrics.inliers = result.inlierIndices.size();
    result.metrics.inlierRatio = static_cast<double>(result.metrics.inliers) /
                                 static_cast<double>(result.metrics.correspondences);
    result.metrics.positionRmseMetres =
        std::sqrt(squaredPositionError / static_cast<double>(result.metrics.inliers));
    result.metrics.positionMedianMetres = percentile(inlierPositions, 0.5);
    result.metrics.positionP95Metres = percentile(inlierPositions, 0.95);
    result.metrics.positionMaximumMetres = *std::ranges::max_element(inlierPositions);
    result.metrics.orientationMedianDegrees = percentile(inlierOrientations, 0.5);
    result.metrics.orientationP95Degrees = percentile(inlierOrientations, 0.95);
    result.metrics.orientationMaximumDegrees = *std::ranges::max_element(inlierOrientations);
    if (result.metrics.inlierRatio < config.minimumInlierRatio)
        result.issues.emplace_back("Camera correspondence inlier ratio is below the quality gate");
    if (result.metrics.positionMedianMetres > config.maximumMedianPositionErrorMetres)
        result.issues.emplace_back("Median metric camera-position error exceeds the quality gate");
    if (result.metrics.positionP95Metres > config.maximumP95PositionErrorMetres)
        result.issues.emplace_back("P95 metric camera-position error exceeds the quality gate");
    if (result.metrics.orientationMedianDegrees > config.maximumMedianOrientationErrorDegrees)
        result.issues.emplace_back("Median camera-orientation error exceeds the quality gate");
    if (result.metrics.orientationP95Degrees > config.maximumP95OrientationErrorDegrees)
        result.issues.emplace_back("P95 camera-orientation error exceeds the quality gate");
    result.accepted = result.issues.empty();
    return result;
}

} // namespace aether::reconstruction
