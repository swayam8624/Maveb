#include <aether/reconstruction/SparseModelValidator.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

namespace aether::reconstruction {
namespace {
struct ImagePose final {
    std::uint64_t id{};
    std::filesystem::path name;
    std::array<double, 3> center{};
    std::array<double, 3> forward{};
};

bool finite(double value) {
    return std::isfinite(value);
}

Result<std::vector<ImagePose>> parseImages(const std::filesystem::path& path) {
    std::ifstream stream(path);
    if (!stream)
        return fail(ErrorCode::notFound, "COLMAP text model is missing images.txt", path);
    std::vector<ImagePose> poses;
    std::unordered_set<std::uint64_t> ids;
    std::set<std::filesystem::path> names;
    std::string line;
    bool expectObservationLine = false;
    while (std::getline(stream, line)) {
        if (line.size() > 16ULL * 1024ULL * 1024ULL)
            return fail(ErrorCode::resourceExhausted,
                        "COLMAP images.txt line exceeds safety limit");
        if (!line.empty() && line.front() == '#')
            continue;
        if (expectObservationLine) {
            std::istringstream observations(line);
            while (true) {
                double x{}, y{};
                std::int64_t pointId{};
                if (!(observations >> x)) {
                    if (observations.eof())
                        break;
                    return fail(ErrorCode::corruptData,
                                "COLMAP POINTS2D line contains an invalid coordinate");
                }
                if (!(observations >> y >> pointId) || !finite(x) || !finite(y) || pointId < -1)
                    return fail(ErrorCode::corruptData,
                                "COLMAP POINTS2D line contains an incomplete observation");
            }
            expectObservationLine = false;
            continue;
        }
        if (line.empty())
            continue;
        std::istringstream values(line);
        std::uint64_t imageId{}, cameraId{};
        double qw{}, qx{}, qy{}, qz{}, tx{}, ty{}, tz{};
        std::string name;
        if (!(values >> imageId >> qw >> qx >> qy >> qz >> tx >> ty >> tz >> cameraId >> name) ||
            imageId == 0 || cameraId == 0 || name.empty() || !finite(qw) || !finite(qx) ||
            !finite(qy) || !finite(qz) || !finite(tx) || !finite(ty) || !finite(tz))
            return fail(ErrorCode::corruptData, "COLMAP images.txt contains an invalid pose line");
        std::filesystem::path imageName(name);
        if (imageName.is_absolute())
            return fail(ErrorCode::corruptData, "COLMAP image name must be relative", name);
        for (const auto& component : imageName)
            if (component == "..")
                return fail(ErrorCode::corruptData, "COLMAP image name contains path traversal",
                            name);
        imageName = imageName.lexically_normal();
        if (!ids.insert(imageId).second)
            return fail(ErrorCode::corruptData, "COLMAP images.txt contains a duplicate image ID");
        if (!names.insert(imageName).second)
            return fail(ErrorCode::corruptData, "COLMAP images.txt contains a duplicate image name",
                        imageName);
        const double length = std::sqrt(qw * qw + qx * qx + qy * qy + qz * qz);
        if (!finite(length) || length < 1.0e-12)
            return fail(ErrorCode::corruptData, "COLMAP image quaternion is degenerate");
        qw /= length;
        qx /= length;
        qy /= length;
        qz /= length;
        const std::array<std::array<double, 3>, 3> rotation{
            {{{1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy - qz * qw),
               2.0 * (qx * qz + qy * qw)}},
             {{2.0 * (qx * qy + qz * qw), 1.0 - 2.0 * (qx * qx + qz * qz),
               2.0 * (qy * qz - qx * qw)}},
             {{2.0 * (qx * qz - qy * qw), 2.0 * (qy * qz + qx * qw),
               1.0 - 2.0 * (qx * qx + qy * qy)}}}};
        const std::array<double, 3> translation{tx, ty, tz};
        ImagePose pose;
        pose.id = imageId;
        pose.name = std::move(imageName);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            pose.center[axis] =
                -(rotation[0][axis] * translation[0] + rotation[1][axis] * translation[1] +
                  rotation[2][axis] * translation[2]);
            pose.forward[axis] = rotation[2][axis];
        }
        poses.push_back(pose);
        expectObservationLine = true;
        if (poses.size() > 10'000'000U)
            return fail(ErrorCode::resourceExhausted,
                        "COLMAP registered-image count exceeds limit");
    }
    if (!stream.eof())
        return fail(ErrorCode::io, "Unable to read COLMAP images.txt", path);
    if (expectObservationLine)
        return fail(ErrorCode::corruptData, "COLMAP images.txt is missing a POINTS2D line");
    return poses;
}

struct TrackGraph final {
    std::size_t points{};
    std::size_t totalTrackLength{};
    std::vector<std::unordered_set<std::size_t>> adjacency;
};

Result<TrackGraph> parseTracks(const std::filesystem::path& path,
                               const std::vector<ImagePose>& poses) {
    std::ifstream stream(path);
    if (!stream)
        return fail(ErrorCode::notFound, "COLMAP text model is missing points3D.txt", path);
    std::unordered_map<std::uint64_t, std::size_t> imageIndices;
    for (std::size_t index = 0; index < poses.size(); ++index)
        imageIndices[poses[index].id] = index;
    TrackGraph graph;
    graph.adjacency.resize(poses.size());
    std::unordered_set<std::uint64_t> pointIds;
    std::string line;
    while (std::getline(stream, line)) {
        if (line.empty() || line.front() == '#')
            continue;
        if (line.size() > 16ULL * 1024ULL * 1024ULL)
            return fail(ErrorCode::resourceExhausted,
                        "COLMAP points3D.txt line exceeds safety limit");
        std::istringstream values(line);
        std::uint64_t pointId{};
        double x{}, y{}, z{}, error{};
        unsigned red{}, green{}, blue{};
        if (!(values >> pointId >> x >> y >> z >> red >> green >> blue >> error) || pointId == 0 ||
            !finite(x) || !finite(y) || !finite(z) || !finite(error) || red > 255 || green > 255 ||
            blue > 255 || !pointIds.insert(pointId).second)
            return fail(ErrorCode::corruptData, "COLMAP points3D.txt contains an invalid point");
        std::vector<std::size_t> track;
        std::uint64_t imageId{}, point2DIndex{};
        while (true) {
            if (!(values >> imageId)) {
                if (values.eof())
                    break;
                return fail(ErrorCode::corruptData,
                            "COLMAP point track contains an invalid image ID");
            }
            if (!(values >> point2DIndex))
                return fail(ErrorCode::corruptData,
                            "COLMAP point track contains an incomplete pair");
            (void)point2DIndex;
            const auto found = imageIndices.find(imageId);
            if (found == imageIndices.end())
                return fail(ErrorCode::corruptData,
                            "COLMAP point track references an unknown image");
            if (std::ranges::find(track, found->second) == track.end())
                track.push_back(found->second);
        }
        if (track.size() < 2)
            continue;
        ++graph.points;
        graph.totalTrackLength += track.size();
        for (std::size_t left = 0; left < track.size(); ++left)
            for (std::size_t right = left + 1; right < track.size(); ++right) {
                graph.adjacency[track[left]].insert(track[right]);
                graph.adjacency[track[right]].insert(track[left]);
            }
        if (graph.points > 100'000'000U)
            return fail(ErrorCode::resourceExhausted, "COLMAP tracked-point count exceeds limit");
    }
    if (!stream.eof())
        return fail(ErrorCode::io, "Unable to read COLMAP points3D.txt", path);
    return graph;
}
} // namespace

Result<SparseCoverageReport>
validateSparseTextModelImpl(const std::filesystem::path& modelDirectory,
                            std::size_t inputImageCount,
                            std::span<const std::filesystem::path> selectedImages,
                            const SparseCoverageThresholds& thresholds) {
    if (inputImageCount == 0 || thresholds.minimumRegisteredImages < 2 ||
        !finite(thresholds.minimumRegistrationRatio) || thresholds.minimumRegistrationRatio <= 0 ||
        thresholds.minimumRegistrationRatio > 1 || thresholds.minimumTrackedPoints == 0 ||
        !finite(thresholds.minimumConnectedImageRatio) ||
        thresholds.minimumConnectedImageRatio <= 0 || thresholds.minimumConnectedImageRatio > 1 ||
        !finite(thresholds.minimumBaseline) || thresholds.minimumBaseline <= 0 ||
        !finite(thresholds.minimumViewAngleDegrees) || thresholds.minimumViewAngleDegrees < 0)
        return fail(ErrorCode::invalidArgument, "Sparse coverage validation arguments are invalid");
    auto poses = parseImages(modelDirectory / "images.txt");
    if (!poses)
        return std::unexpected(poses.error());
    auto graph = parseTracks(modelDirectory / "points3D.txt", *poses);
    if (!graph)
        return std::unexpected(graph.error());
    SparseCoverageReport report;
    report.inputImages = inputImageCount;
    report.registeredImages = poses->size();
    report.trackedPoints = graph->points;
    report.registrationRatio = std::min(1.0, static_cast<double>(report.registeredImages) /
                                                 static_cast<double>(inputImageCount));
    report.meanTrackLength = graph->points == 0 ? 0.0
                                                : static_cast<double>(graph->totalTrackLength) /
                                                      static_cast<double>(graph->points);
    std::vector<bool> visited(poses->size());
    for (std::size_t start = 0; start < poses->size(); ++start) {
        if (visited[start])
            continue;
        std::vector<std::size_t> pending{start};
        visited[start] = true;
        std::size_t component = 0;
        while (!pending.empty()) {
            const auto node = pending.back();
            pending.pop_back();
            ++component;
            for (const auto neighbor : graph->adjacency[node])
                if (!visited[neighbor]) {
                    visited[neighbor] = true;
                    pending.push_back(neighbor);
                }
        }
        report.connectedImages = std::max(report.connectedImages, component);
    }
    report.connectedImageRatio = poses->empty() ? 0.0
                                                : static_cast<double>(report.connectedImages) /
                                                      static_cast<double>(poses->size());
    if (!poses->empty()) {
        auto minimum = poses->front().center;
        auto maximum = poses->front().center;
        for (const auto& pose : *poses)
            for (std::size_t axis = 0; axis < 3; ++axis) {
                minimum[axis] = std::min(minimum[axis], pose.center[axis]);
                maximum[axis] = std::max(maximum[axis], pose.center[axis]);
            }
        double squared = 0;
        for (std::size_t axis = 0; axis < 3; ++axis)
            squared += (maximum[axis] - minimum[axis]) * (maximum[axis] - minimum[axis]);
        report.baselineDiagonal = std::sqrt(squared);
        constexpr double radiansToDegrees = 57.29577951308232;
        for (std::size_t left = 0; left < poses->size(); ++left)
            for (std::size_t right = left + 1; right < poses->size(); ++right) {
                double dot = 0;
                for (std::size_t axis = 0; axis < 3; ++axis)
                    dot += (*poses)[left].forward[axis] * (*poses)[right].forward[axis];
                report.maximumViewAngleDegrees =
                    std::max(report.maximumViewAngleDegrees,
                             std::acos(std::clamp(dot, -1.0, 1.0)) * radiansToDegrees);
            }
    }
    if (report.registeredImages < thresholds.minimumRegisteredImages)
        report.issues.emplace_back("Too few images registered in the sparse model");
    if (report.registeredImages > inputImageCount)
        report.issues.emplace_back("Sparse model contains images outside the validated input set");
    if (!selectedImages.empty()) {
        std::set<std::filesystem::path> expected;
        for (const auto& selected : selectedImages) {
            if (selected.empty() || selected.is_absolute())
                return fail(ErrorCode::invalidArgument,
                            "Selected sparse-model image path must be relative", selected);
            auto normalized = selected.lexically_normal();
            for (const auto& component : normalized)
                if (component == "..")
                    return fail(ErrorCode::invalidArgument,
                                "Selected sparse-model image path contains traversal", selected);
            if (!expected.insert(std::move(normalized)).second)
                return fail(ErrorCode::invalidArgument,
                            "Selected sparse-model image path is duplicated", selected);
        }
        for (const auto& pose : *poses)
            if (!expected.contains(pose.name))
                report.issues.emplace_back("Sparse model registered an image outside the exact "
                                           "selected input list: " +
                                           pose.name.generic_string());
    }
    if (report.registrationRatio < thresholds.minimumRegistrationRatio)
        report.issues.emplace_back("Registered-image ratio is below the required coverage");
    if (report.trackedPoints < thresholds.minimumTrackedPoints)
        report.issues.emplace_back("Too few multi-view 3D point tracks were reconstructed");
    if (report.connectedImageRatio < thresholds.minimumConnectedImageRatio)
        report.issues.emplace_back("Image overlap graph is fragmented");
    if (report.baselineDiagonal < thresholds.minimumBaseline)
        report.issues.emplace_back("Registered camera centers have degenerate baseline");
    if (report.maximumViewAngleDegrees < thresholds.minimumViewAngleDegrees)
        report.issues.emplace_back("Registered cameras lack angular diversity");
    return report;
}

Result<SparseCoverageReport> validateSparseTextModel(const std::filesystem::path& modelDirectory,
                                                     std::size_t inputImageCount,
                                                     const SparseCoverageThresholds& thresholds) {
    return validateSparseTextModelImpl(modelDirectory, inputImageCount, {}, thresholds);
}

Result<SparseCoverageReport>
validateSparseTextModel(const std::filesystem::path& modelDirectory,
                        std::span<const std::filesystem::path> selectedImages,
                        const SparseCoverageThresholds& thresholds) {
    if (selectedImages.empty())
        return fail(ErrorCode::invalidArgument, "Selected sparse-model image list is empty");
    return validateSparseTextModelImpl(modelDirectory, selectedImages.size(), selectedImages,
                                       thresholds);
}

Result<SparseModelSelection>
selectBestSparseModel(const std::vector<SparseModelCandidate>& candidates) {
    if (candidates.empty())
        return fail(ErrorCode::notFound, "COLMAP did not produce a sparse model");
    std::optional<std::size_t> selected;
    auto rank = [](const SparseModelCandidate& candidate) {
        const auto& coverage = candidate.coverage;
        return std::tuple{coverage.connectedImages,         coverage.registeredImages,
                          coverage.trackedPoints,           coverage.meanTrackLength,
                          coverage.maximumViewAngleDegrees, coverage.baselineDiagonal};
    };
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        if (!candidates[index].coverage.passed())
            continue;
        if (!selected || rank(candidates[index]) > rank(candidates[*selected]))
            selected = index;
    }
    if (!selected) {
        std::string context;
        for (const auto& candidate : candidates) {
            if (!context.empty())
                context += " · ";
            context += candidate.id + ":";
            if (candidate.coverage.issues.empty())
                context += "invalid";
            else
                for (std::size_t index = 0; index < candidate.coverage.issues.size(); ++index) {
                    if (index > 0)
                        context += ",";
                    context += candidate.coverage.issues[index];
                }
        }
        return fail(ErrorCode::unsupported, "No sparse model passed the coverage gate", context);
    }
    const auto& winner = candidates[*selected];
    std::ostringstream reason;
    reason << "Selected model " << winner.id << " from " << candidates.size()
           << " candidates: largest connected image set (" << winner.coverage.connectedImages
           << "), then registered images (" << winner.coverage.registeredImages
           << "), tracked points (" << winner.coverage.trackedPoints << "), mean track length ("
           << winner.coverage.meanTrackLength << "), angular diversity ("
           << winner.coverage.maximumViewAngleDegrees << " deg), and baseline ("
           << winner.coverage.baselineDiagonal << ")";
    return SparseModelSelection{*selected, reason.str()};
}

} // namespace aether::reconstruction
