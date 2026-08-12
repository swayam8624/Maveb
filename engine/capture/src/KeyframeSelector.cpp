#include <aether/capture/KeyframeSelector.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::capture {
namespace {
bool finite(double value) {
    return std::isfinite(value);
}

double appearanceDistance(const ImageMeasurement& left, const ImageMeasurement& right) {
    const auto& a = left.appearanceFingerprint;
    const auto& b = right.appearanceFingerprint;
    double meanA = 0.0;
    double meanB = 0.0;
    for (std::size_t index = 0; index < a.size(); ++index) {
        meanA += static_cast<double>(a[index]);
        meanB += static_cast<double>(b[index]);
    }
    meanA /= static_cast<double>(a.size());
    meanB /= static_cast<double>(b.size());
    double covariance = 0.0;
    double varianceA = 0.0;
    double varianceB = 0.0;
    for (std::size_t index = 0; index < a.size(); ++index) {
        const double deltaA = static_cast<double>(a[index]) - meanA;
        const double deltaB = static_cast<double>(b[index]) - meanB;
        covariance += deltaA * deltaB;
        varianceA += deltaA * deltaA;
        varianceB += deltaB * deltaB;
    }
    const double denominator = std::sqrt(varianceA * varianceB);
    if (denominator <= std::numeric_limits<double>::epsilon())
        return 1.0;
    const double correlation = std::clamp(covariance / denominator, -1.0, 1.0);
    return 0.5 * (1.0 - correlation);
}

bool validOptions(const KeyframeSelectionOptions& options) {
    return options.minimumSelectedImages >= 3 && options.minimumFrameGap > 0 &&
           options.maximumFrameGap >= options.minimumFrameGap &&
           finite(options.relativeSharpnessThreshold) &&
           options.relativeSharpnessThreshold >= 0.0 && options.relativeSharpnessThreshold <= 1.0 &&
           finite(options.minimumMeanLuminance) && finite(options.maximumMeanLuminance) &&
           options.minimumMeanLuminance >= 0.0 &&
           options.minimumMeanLuminance < options.maximumMeanLuminance &&
           options.maximumMeanLuminance <= 1.0 && finite(options.minimumLuminanceDeviation) &&
           options.minimumLuminanceDeviation >= 0.0 && finite(options.minimumAppearanceDistance) &&
           options.minimumAppearanceDistance >= 0.0 && finite(options.maximumAppearanceDistance) &&
           options.maximumAppearanceDistance > options.minimumAppearanceDistance &&
           options.maximumAppearanceDistance <= 1.0;
}
} // namespace

KeyframeSelectionReport selectKeyframes(const CaptureReport& capture,
                                        const KeyframeSelectionOptions& options) {
    KeyframeSelectionReport report;
    report.medianSharpness = capture.medianSharpness;
    if (!validOptions(options)) {
        report.issues.emplace_back("Keyframe selection options are invalid");
        return report;
    }
    if (!capture.valid())
        report.issues.emplace_back("Capture validation failed before keyframe selection");
    if (capture.images.empty()) {
        report.issues.emplace_back("No decoded images are available for keyframe selection");
        return report;
    }

    std::optional<std::size_t> lastSelected;
    report.decisions.reserve(capture.images.size());
    for (std::size_t index = 0; index < capture.images.size(); ++index) {
        const auto& image = capture.images[index];
        KeyframeDecision decision{image.path, false, {}, 0.0};
        if (report.medianSharpness > 0.0 &&
            image.sharpness < report.medianSharpness * options.relativeSharpnessThreshold) {
            decision.reason = "relative-blur";
        } else if (image.meanLuminance < options.minimumMeanLuminance) {
            decision.reason = "underexposed";
        } else if (image.meanLuminance > options.maximumMeanLuminance) {
            decision.reason = "overexposed";
        } else if (image.luminanceDeviation < options.minimumLuminanceDeviation) {
            decision.reason = "low-contrast";
        } else if (!lastSelected) {
            decision.selected = true;
            decision.reason = "sequence-start";
        } else {
            const std::size_t frameGap = index - *lastSelected;
            decision.appearanceDistance = appearanceDistance(capture.images[*lastSelected], image);
            if (frameGap < options.minimumFrameGap) {
                decision.reason = "minimum-spacing";
            } else if (decision.appearanceDistance > options.maximumAppearanceDistance) {
                decision.reason = "appearance-discontinuity";
            } else {
                const double minimumDistance = frameGap >= options.maximumFrameGap
                                                   ? options.minimumAppearanceDistance * 0.25
                                                   : options.minimumAppearanceDistance;
                if (decision.appearanceDistance < minimumDistance) {
                    decision.reason = "near-duplicate";
                } else {
                    decision.selected = true;
                    decision.reason =
                        frameGap >= options.maximumFrameGap ? "maximum-gap" : "useful-change";
                }
            }
        }
        if (decision.selected) {
            lastSelected = index;
            report.selectedImages.push_back(image.path);
        }
        report.decisions.push_back(std::move(decision));
    }
    if (report.selectedImages.size() < options.minimumSelectedImages)
        report.issues.emplace_back("Too few useful keyframes remain after deterministic admission");
    return report;
}

} // namespace aether::capture
