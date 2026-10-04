#include <aether/reconstruction/GeometryEvaluation.hpp>

#include <cmath>
#include <limits>

namespace aether::reconstruction {
namespace {

constexpr std::size_t maximumPoints = 100'000;
constexpr std::size_t maximumComparisons = 100'000'000;

double squaredDistance(const std::array<double, 3>& a, const std::array<double, 3>& b) {
    const auto x = a[0] - b[0];
    const auto y = a[1] - b[1];
    const auto z = a[2] - b[2];
    return x * x + y * y + z * z;
}

double nearestDistance(const std::array<double, 3>& point,
                       const std::vector<std::array<double, 3>>& candidates) {
    auto nearest = std::numeric_limits<double>::infinity();
    for (const auto& candidate : candidates)
        nearest = std::min(nearest, squaredDistance(point, candidate));
    return std::sqrt(nearest);
}

} // namespace

Result<GeometryMetrics>
evaluateGeometry(const mesh::MeshAsset& prediction,
                 const std::vector<std::array<double, 3>>& referencePoints,
                 double fScoreThresholdMetres) {
    if (referencePoints.empty() || referencePoints.size() > maximumPoints ||
        !std::isfinite(fScoreThresholdMetres) || fScoreThresholdMetres <= 0.0)
        return fail(ErrorCode::invalidArgument,
                    "Geometry reference or F-score threshold is invalid");

    std::vector<std::array<double, 3>> vertices;
    GeometryMetrics metrics;
    for (const auto& primitive : prediction.primitives) {
        const auto base = vertices.size();
        if (primitive.vertices.size() > maximumPoints - vertices.size())
            return fail(ErrorCode::resourceExhausted,
                        "Geometry evaluation vertex budget exceeded");
        for (const auto& vertex : primitive.vertices) {
            const std::array<double, 3> point{vertex.position.x, vertex.position.y,
                                               vertex.position.z};
            if (!std::isfinite(point[0]) || !std::isfinite(point[1]) ||
                !std::isfinite(point[2]))
                return fail(ErrorCode::corruptData,
                            "Prediction contains a non-finite vertex");
            vertices.push_back(point);
        }
        for (std::size_t index = 0; index + 2 < primitive.indices.size(); index += 3) {
            const auto a = primitive.indices[index];
            const auto b = primitive.indices[index + 1];
            const auto c = primitive.indices[index + 2];
            if (a >= primitive.vertices.size() || b >= primitive.vertices.size() ||
                c >= primitive.vertices.size()) {
                ++metrics.invalidIndices;
                continue;
            }
            if (a == b || b == c || a == c) {
                ++metrics.degenerateTriangles;
                continue;
            }
            const auto& pa = vertices[base + a];
            const auto& pb = vertices[base + b];
            const auto& pc = vertices[base + c];
            const std::array<double, 3> ab{pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]};
            const std::array<double, 3> ac{pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]};
            const std::array<double, 3> cross{
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            };
            if (cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2] <
                1.0e-20)
                ++metrics.degenerateTriangles;
        }
    }
    if (vertices.empty())
        return fail(ErrorCode::invalidArgument, "Prediction contains no vertices");
    if (vertices.size() > maximumComparisons / referencePoints.size())
        return fail(ErrorCode::resourceExhausted,
                    "Geometry evaluation comparison budget exceeded");

    double accuracy = 0.0;
    std::size_t accurate = 0;
    for (const auto& vertex : vertices) {
        const auto distance = nearestDistance(vertex, referencePoints);
        accuracy += distance;
        accurate += distance <= fScoreThresholdMetres ? 1 : 0;
    }
    double completeness = 0.0;
    std::size_t complete = 0;
    for (const auto& reference : referencePoints) {
        const auto distance = nearestDistance(reference, vertices);
        completeness += distance;
        complete += distance <= fScoreThresholdMetres ? 1 : 0;
    }
    metrics.accuracyMeanMetres = accuracy / static_cast<double>(vertices.size());
    metrics.completenessMeanMetres =
        completeness / static_cast<double>(referencePoints.size());
    metrics.chamferMeanMetres =
        0.5 * (metrics.accuracyMeanMetres + metrics.completenessMeanMetres);
    const auto precision = static_cast<double>(accurate) / static_cast<double>(vertices.size());
    const auto recall =
        static_cast<double>(complete) / static_cast<double>(referencePoints.size());
    metrics.fScore = precision + recall > 0.0
                         ? 2.0 * precision * recall / (precision + recall)
                         : 0.0;
    metrics.evaluatedVertices = vertices.size();
    metrics.referencePoints = referencePoints.size();
    return metrics;
}

} // namespace aether::reconstruction
