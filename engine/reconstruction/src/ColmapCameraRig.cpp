#include <aether/reconstruction/ColmapCameraRig.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <fstream>
#include <sstream>
#include <unordered_set>

namespace aether::reconstruction {
namespace {

using Quaternion = std::array<double, 4>;
using Vector3 = std::array<double, 3>;

Quaternion normalized(Quaternion value) {
    const double magnitude = std::sqrt(value[0] * value[0] + value[1] * value[1] +
                                       value[2] * value[2] + value[3] * value[3]);
    for (auto& component : value)
        component /= magnitude;
    return value;
}

Vector3 rotate(const Quaternion& quaternion, const Vector3& value) {
    const Vector3 imaginary{quaternion[1], quaternion[2], quaternion[3]};
    const Vector3 firstCross{imaginary[1] * value[2] - imaginary[2] * value[1],
                             imaginary[2] * value[0] - imaginary[0] * value[2],
                             imaginary[0] * value[1] - imaginary[1] * value[0]};
    const Vector3 twiceCross{2.0 * firstCross[0], 2.0 * firstCross[1], 2.0 * firstCross[2]};
    const Vector3 secondCross{imaginary[1] * twiceCross[2] - imaginary[2] * twiceCross[1],
                              imaginary[2] * twiceCross[0] - imaginary[0] * twiceCross[2],
                              imaginary[0] * twiceCross[1] - imaginary[1] * twiceCross[0]};
    return {value[0] + quaternion[0] * twiceCross[0] + secondCross[0],
            value[1] + quaternion[0] * twiceCross[1] + secondCross[1],
            value[2] + quaternion[0] * twiceCross[2] + secondCross[2]};
}

std::string trimLeft(std::string value) {
    value.erase(value.begin(), std::ranges::find_if(value, [](unsigned char character) {
                    return !std::isspace(character);
                }));
    return value;
}

} // namespace

Result<std::vector<ColmapCameraRecord>> loadColmapCameraRig(const std::filesystem::path& imagesText,
                                                            const ColmapCameraRigLimits& limits) {
    if (limits.maximumImages == 0 || limits.maximumLineBytes == 0)
        return fail(ErrorCode::invalidArgument, "COLMAP camera-rig limits are invalid");
    std::ifstream stream(imagesText);
    if (!stream)
        return fail(ErrorCode::notFound, "COLMAP text model is missing images.txt", imagesText);
    std::vector<ColmapCameraRecord> result;
    std::unordered_set<std::uint64_t> imageIds;
    std::unordered_set<std::string> imageNames;
    std::string line;
    bool expectObservations = false;
    while (std::getline(stream, line)) {
        if (line.size() > limits.maximumLineBytes)
            return fail(ErrorCode::resourceExhausted,
                        "COLMAP images.txt line exceeds its safety limit");
        if (!line.empty() && line.front() == '#')
            continue;
        if (expectObservations) {
            std::istringstream observations(line);
            while (true) {
                double x{};
                double y{};
                std::int64_t pointId{};
                if (!(observations >> x)) {
                    if (observations.eof())
                        break;
                    return fail(ErrorCode::corruptData,
                                "COLMAP POINTS2D line contains an invalid coordinate");
                }
                if (!(observations >> y >> pointId) || !std::isfinite(x) || !std::isfinite(y) ||
                    pointId < -1)
                    return fail(ErrorCode::corruptData,
                                "COLMAP POINTS2D line contains an incomplete observation");
            }
            expectObservations = false;
            continue;
        }
        if (line.empty())
            continue;
        std::istringstream values(line);
        std::uint64_t imageId{};
        std::uint64_t cameraId{};
        Quaternion worldToCamera{};
        Vector3 translation{};
        if (!(values >> imageId >> worldToCamera[0] >> worldToCamera[1] >> worldToCamera[2] >>
              worldToCamera[3] >> translation[0] >> translation[1] >> translation[2] >> cameraId) ||
            imageId == 0 || cameraId == 0 ||
            !std::ranges::all_of(worldToCamera,
                                 [](double value) { return std::isfinite(value); }) ||
            !std::ranges::all_of(translation, [](double value) { return std::isfinite(value); }))
            return fail(ErrorCode::corruptData, "COLMAP images.txt contains an invalid pose line");
        std::string imageName;
        std::getline(values, imageName);
        imageName = trimLeft(std::move(imageName));
        const std::filesystem::path relativeName(imageName);
        if (imageName.empty() || relativeName.is_absolute() ||
            std::ranges::any_of(relativeName,
                                [](const auto& component) { return component == ".."; }))
            return fail(ErrorCode::corruptData, "COLMAP image name must be a safe relative path",
                        imageName);
        const double magnitude =
            std::sqrt(worldToCamera[0] * worldToCamera[0] + worldToCamera[1] * worldToCamera[1] +
                      worldToCamera[2] * worldToCamera[2] + worldToCamera[3] * worldToCamera[3]);
        if (!std::isfinite(magnitude) || magnitude <= 1.0e-12)
            return fail(ErrorCode::corruptData, "COLMAP image quaternion is degenerate", imageName);
        worldToCamera = normalized(worldToCamera);
        Quaternion cameraToWorld{worldToCamera[0], -worldToCamera[1], -worldToCamera[2],
                                 -worldToCamera[3]};
        const Vector3 negativeTranslation{-translation[0], -translation[1], -translation[2]};
        const auto center = rotate(cameraToWorld, negativeTranslation);
        if (!imageIds.insert(imageId).second || !imageNames.insert(imageName).second)
            return fail(ErrorCode::corruptData,
                        "COLMAP images.txt contains a duplicate image ID or name", imageName);
        result.push_back(ColmapCameraRecord{imageId, cameraId, std::move(imageName),
                                            AlignmentCameraPose{center, cameraToWorld}});
        if (result.size() > limits.maximumImages)
            return fail(ErrorCode::resourceExhausted,
                        "COLMAP registered-image count exceeds its limit");
        expectObservations = true;
    }
    if (!stream.eof())
        return fail(ErrorCode::io, "Unable to read COLMAP images.txt", imagesText);
    if (expectObservations)
        return fail(ErrorCode::corruptData, "COLMAP images.txt is missing a POINTS2D line");
    if (result.empty())
        return fail(ErrorCode::corruptData, "COLMAP images.txt contains no registered cameras");
    return result;
}

} // namespace aether::reconstruction
