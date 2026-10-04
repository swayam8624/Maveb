#include <aether/scene/CameraPath.hpp>

#include <simdjson.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>

namespace aether::scene {
namespace {

Result<std::vector<double>> readNumberArray(simdjson::dom::element object, const char* field,
                                            std::size_t expectedCount) {
    simdjson::dom::array array;
    if (object[field].get_array().get(array) || array.size() != expectedCount)
        return fail(ErrorCode::corruptData, "Camera path array has an invalid size", field);
    std::vector<double> result;
    result.reserve(expectedCount);
    for (simdjson::dom::element value : array) {
        double number{};
        if (value.get(number) || !std::isfinite(number))
            return fail(ErrorCode::corruptData, "Camera path array contains a non-finite number",
                        field);
        result.push_back(number);
    }
    return result;
}

Result<double> readNumber(simdjson::dom::element object, const char* field) {
    double value{};
    if (object[field].get(value) || !std::isfinite(value))
        return fail(ErrorCode::corruptData, "Camera path field is missing or non-finite", field);
    return value;
}

} // namespace

Result<CameraPath> CameraPath::load(const std::filesystem::path& path,
                                    std::size_t maximumKeyframes) {
    simdjson::dom::parser parser;
    auto parsed = parser.load(path.string());
    if (parsed.error())
        return fail(ErrorCode::corruptData, "Unable to parse camera path JSON",
                    simdjson::error_message(parsed.error()));
    simdjson::dom::element document = parsed.value();
    std::uint64_t schemaVersion{};
    if (document["schemaVersion"].get(schemaVersion) || schemaVersion != 1)
        return fail(ErrorCode::unsupported, "Camera path schema version is unsupported");
    simdjson::dom::array keyframes;
    if (document["keyframes"].get_array().get(keyframes) || keyframes.size() == 0 ||
        keyframes.size() > maximumKeyframes)
        return fail(ErrorCode::resourceExhausted, "Camera path keyframe count is invalid");

    CameraPath result;
    result.keyframes_.reserve(keyframes.size());
    for (simdjson::dom::element element : keyframes) {
        auto seconds = readNumber(element, "time");
        auto position = readNumberArray(element, "position", 3);
        auto rotation = readNumberArray(element, "rotation", 4);
        auto fieldOfView = readNumber(element, "verticalFovRadians");
        auto exposure = readNumber(element, "exposureEv");
        if (!seconds)
            return std::unexpected(seconds.error());
        if (!position)
            return std::unexpected(position.error());
        if (!rotation)
            return std::unexpected(rotation.error());
        if (!fieldOfView)
            return std::unexpected(fieldOfView.error());
        if (!exposure)
            return std::unexpected(exposure.error());
        CameraKeyframe keyframe;
        keyframe.seconds = *seconds;
        keyframe.transform.translation = {static_cast<float>((*position)[0]),
                                          static_cast<float>((*position)[1]),
                                          static_cast<float>((*position)[2])};
        keyframe.transform.rotation =
            simd_quaternion(static_cast<float>((*rotation)[0]), static_cast<float>((*rotation)[1]),
                            static_cast<float>((*rotation)[2]), static_cast<float>((*rotation)[3]));
        keyframe.transform.rotation = simd_normalize(keyframe.transform.rotation);
        keyframe.verticalFieldOfViewRadians = static_cast<float>(*fieldOfView);
        keyframe.exposureEv = static_cast<float>(*exposure);
        result.keyframes_.push_back(keyframe);
    }
    if (auto validated = result.validate(); !validated)
        return std::unexpected(validated.error());
    return result;
}

Result<void> CameraPath::save(const std::filesystem::path& path) const {
    if (auto validated = validate(); !validated)
        return validated;
    if (path.empty())
        return fail(ErrorCode::invalidArgument, "Camera path destination is empty");
    const auto temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    stream << std::setprecision(std::numeric_limits<double>::max_digits10);
    stream << "{\n  \"schemaVersion\": 1,\n  \"keyframes\": [\n";
    for (std::size_t index = 0; index < keyframes_.size(); ++index) {
        const CameraKeyframe& keyframe = keyframes_[index];
        const simd_float4 rotation = keyframe.transform.rotation.vector;
        stream << "    {\"time\":" << keyframe.seconds << ",\"position\":["
               << keyframe.transform.translation.x << ',' << keyframe.transform.translation.y << ','
               << keyframe.transform.translation.z << "],\"rotation\":[" << rotation.x << ','
               << rotation.y << ',' << rotation.z << ',' << rotation.w
               << "],\"verticalFovRadians\":" << keyframe.verticalFieldOfViewRadians
               << ",\"exposureEv\":" << keyframe.exposureEv << '}';
        stream << (index + 1 == keyframes_.size() ? "\n" : ",\n");
    }
    stream << "  ]\n}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to write camera path", path.string());
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to finalize camera path", error.message());
    }
    return {};
}

Result<CameraKeyframe> CameraPath::sample(double seconds) const {
    if (!std::isfinite(seconds))
        return fail(ErrorCode::invalidArgument, "Camera path sample time is non-finite");
    if (auto validated = validate(); !validated)
        return std::unexpected(validated.error());
    if (seconds <= keyframes_.front().seconds)
        return keyframes_.front();
    if (seconds >= keyframes_.back().seconds)
        return keyframes_.back();
    const auto upper = std::ranges::upper_bound(keyframes_, seconds, {}, &CameraKeyframe::seconds);
    const CameraKeyframe& after = *upper;
    const CameraKeyframe& before = *(upper - 1);
    const float amount =
        static_cast<float>((seconds - before.seconds) / (after.seconds - before.seconds));
    CameraKeyframe result;
    result.seconds = seconds;
    result.transform.translation =
        simd_mix(before.transform.translation, after.transform.translation,
                 simd_float3{amount, amount, amount});
    result.transform.rotation =
        simd_slerp(before.transform.rotation, after.transform.rotation, amount);
    result.verticalFieldOfViewRadians =
        std::lerp(before.verticalFieldOfViewRadians, after.verticalFieldOfViewRadians, amount);
    result.exposureEv = std::lerp(before.exposureEv, after.exposureEv, amount);
    return result;
}

double CameraPath::duration() const noexcept {
    return keyframes_.empty() ? 0.0 : keyframes_.back().seconds;
}

Result<void> CameraPath::validate() const {
    if (keyframes_.empty())
        return fail(ErrorCode::invalidArgument, "Camera path contains no keyframes");
    double previous = -1.0;
    for (const CameraKeyframe& keyframe : keyframes_) {
        if (!std::isfinite(keyframe.seconds) || keyframe.seconds < 0.0 ||
            keyframe.seconds <= previous || !isFinite(keyframe.transform) ||
            !std::isfinite(keyframe.verticalFieldOfViewRadians) ||
            keyframe.verticalFieldOfViewRadians <= 0.0F ||
            keyframe.verticalFieldOfViewRadians >= 3.1415926535F ||
            !std::isfinite(keyframe.exposureEv) || std::abs(keyframe.exposureEv) > 32.0F) {
            return fail(ErrorCode::invalidArgument,
                        "Camera path keyframes must be finite and strictly time ordered");
        }
        const float quaternionLength = simd_length(keyframe.transform.rotation.vector);
        if (std::abs(quaternionLength - 1.0F) > 1.0e-3F)
            return fail(ErrorCode::invalidArgument, "Camera path quaternion is not normalized");
        previous = keyframe.seconds;
    }
    return {};
}

} // namespace aether::scene
