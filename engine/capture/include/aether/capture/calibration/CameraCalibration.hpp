#pragma once

#include <string>
#include <array>
#include <cstdint>
#include <optional>

namespace aether::capture {

enum class DistortionModel {
    None,
    Radial,
    Opencv
};

struct CameraCalibration {
    std::string id;
    std::string cameraMake;
    std::string cameraModel;
    std::string lensModel;

    uint32_t width;
    uint32_t height;

    double fx;
    double fy;
    double cx;
    double cy;

    DistortionModel distortionModel{DistortionModel::None};
    std::array<double, 8> distortion{};

    std::optional<double> calibrationRms;
    std::string createdAt;
};

} // namespace aether::capture
