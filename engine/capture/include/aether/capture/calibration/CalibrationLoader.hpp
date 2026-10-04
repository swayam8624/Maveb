#pragma once

#include "CameraCalibration.hpp"
#include <filesystem>
#include <aether/core/Error.hpp>

namespace aether::capture {

class CalibrationLoader {
public:
    static aether::Result<CameraCalibration> load(const std::filesystem::path& path);
};

} // namespace aether::capture
