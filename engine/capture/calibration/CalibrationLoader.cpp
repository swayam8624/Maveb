#include <aether/capture/calibration/CalibrationLoader.hpp>
#include <simdjson.h>
#include <cmath>

namespace aether::capture {
namespace {

aether::Result<double> readNumber(simdjson::dom::element object, const char* field) {
    double value{};
    if (object[field].get(value) || !std::isfinite(value))
        return aether::fail(aether::ErrorCode::corruptData, "Calibration field is missing or non-finite", field);
    return value;
}

aether::Result<std::string> readString(simdjson::dom::element object, const char* field) {
    std::string_view value;
    if (object[field].get(value))
        return aether::fail(aether::ErrorCode::corruptData, "Calibration field is missing or not a string", field);
    return std::string(value);
}

aether::Result<uint32_t> readUint32(simdjson::dom::element object, const char* field) {
    uint64_t value{};
    if (object[field].get(value))
        return aether::fail(aether::ErrorCode::corruptData, "Calibration field is missing or not an integer", field);
    return static_cast<uint32_t>(value);
}

} // namespace

aether::Result<CameraCalibration> CalibrationLoader::load(const std::filesystem::path& path) {
    simdjson::dom::parser parser;
    auto parsed = parser.load(path.string());
    if (parsed.error())
        return aether::fail(aether::ErrorCode::corruptData, "Unable to parse calibration JSON",
                    simdjson::error_message(parsed.error()));
    
    simdjson::dom::element document = parsed.value();
    
    CameraCalibration result;
    
    auto id = readString(document, "id");
    if (!id) return aether::fail(id.error().code, id.error().message, id.error().context);
    result.id = *id;
    
    if (auto make = readString(document, "cameraMake")) result.cameraMake = *make;
    if (auto model = readString(document, "cameraModel")) result.cameraModel = *model;
    if (auto lens = readString(document, "lensModel")) result.lensModel = *lens;
    if (auto created = readString(document, "createdAt")) result.createdAt = *created;
    
    auto width = readUint32(document, "width");
    if (!width) return aether::fail(width.error().code, width.error().message, width.error().context);
    result.width = *width;
    
    auto height = readUint32(document, "height");
    if (!height) return aether::fail(height.error().code, height.error().message, height.error().context);
    result.height = *height;
    
    auto fx = readNumber(document, "fx");
    if (!fx) return aether::fail(fx.error().code, fx.error().message, fx.error().context);
    result.fx = *fx;
    
    auto fy = readNumber(document, "fy");
    if (!fy) return aether::fail(fy.error().code, fy.error().message, fy.error().context);
    result.fy = *fy;
    
    auto cx = readNumber(document, "cx");
    if (!cx) return aether::fail(cx.error().code, cx.error().message, cx.error().context);
    result.cx = *cx;
    
    auto cy = readNumber(document, "cy");
    if (!cy) return aether::fail(cy.error().code, cy.error().message, cy.error().context);
    result.cy = *cy;
    
    if (auto distModel = readString(document, "distortionModel")) {
        if (*distModel == "None") result.distortionModel = DistortionModel::None;
        else if (*distModel == "Radial") result.distortionModel = DistortionModel::Radial;
        else if (*distModel == "Opencv") result.distortionModel = DistortionModel::Opencv;
        else return aether::fail(aether::ErrorCode::corruptData, "Invalid distortion model");
    }
    
    simdjson::dom::array distortionArray;
    if (!document["distortion"].get_array().get(distortionArray)) {
        if (distortionArray.size() != 8) {
            return aether::fail(aether::ErrorCode::corruptData, "Distortion array must have 8 elements");
        }
        size_t i = 0;
        for (simdjson::dom::element value : distortionArray) {
            double number{};
            if (value.get(number) || !std::isfinite(number))
                return aether::fail(aether::ErrorCode::corruptData, "Distortion array contains invalid number");
            result.distortion[i++] = number;
        }
    }
    
    if (auto rms = readNumber(document, "calibrationRms")) {
        result.calibrationRms = *rms;
    }
    
    return result;
}

} // namespace aether::capture
