#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace aether::capture {

struct ImageMeasurement {
    static constexpr std::size_t fingerprintWidth = 16;
    static constexpr std::size_t fingerprintHeight = 16;

    std::filesystem::path path;
    std::uint64_t fileBytes{};
    std::size_t width{};
    std::size_t height{};
    double meanLuminance{};
    double luminanceDeviation{};
    double sharpness{};
    std::optional<double> exposureSeconds;
    std::optional<double> fNumber;
    std::optional<double> iso;
    std::optional<double> focalLengthMillimetres;
    std::string cameraMake;
    std::string cameraModel;
    std::array<std::uint8_t, fingerprintWidth * fingerprintHeight> appearanceFingerprint{};
};

struct CaptureIssue {
    enum class Severity { warning, error };
    Severity severity{Severity::warning};
    std::string code;
    std::string message;
    std::optional<std::filesystem::path> path;
};

struct CaptureReport {
    std::filesystem::path root;
    std::vector<ImageMeasurement> images;
    std::vector<CaptureIssue> issues;
    std::uint64_t sourceBytes{};
    std::uint64_t estimatedWorkingBytes{};
    double medianSharpness{};
    double exposureSpreadStops{};

    [[nodiscard]] bool valid() const;
};

struct ValidationOptions {
    std::size_t minimumImages{3};
    std::size_t analysisMaximumDimension{1024};
    double relativeBlurWarning{0.35};
    double exposureSpreadWarningStops{1.5};
};

[[nodiscard]] CaptureReport validateCapture(const std::filesystem::path& input,
                                            const ValidationOptions& options = {});

} // namespace aether::capture
