#pragma once

#include <aether/capture/CaptureValidator.hpp>

#include <filesystem>
#include <string>
#include <vector>

namespace aether::capture {

struct KeyframeSelectionOptions final {
    std::size_t minimumSelectedImages{3};
    std::size_t minimumFrameGap{2};
    std::size_t maximumFrameGap{30};
    double relativeSharpnessThreshold{0.35};
    double minimumMeanLuminance{0.02};
    double maximumMeanLuminance{0.98};
    double minimumLuminanceDeviation{0.015};
    double minimumAppearanceDistance{0.015};
    double maximumAppearanceDistance{0.65};
};

struct KeyframeDecision final {
    std::filesystem::path path;
    bool selected{};
    std::string reason;
    double appearanceDistance{};
};

struct KeyframeSelectionReport final {
    std::vector<KeyframeDecision> decisions;
    std::vector<std::filesystem::path> selectedImages;
    std::vector<std::string> issues;
    double medianSharpness{};

    [[nodiscard]] bool valid() const noexcept {
        return issues.empty();
    }
};

/// Input: ordered, decoded image measurements from one video frame sequence.
/// Output: deterministic frame decisions and an ordered reconstruction image list.
/// Task: reject blur, exposure failures, duplicates, and discontinuities before SfM.
[[nodiscard]] KeyframeSelectionReport selectKeyframes(const CaptureReport& capture,
                                                      const KeyframeSelectionOptions& options = {});

} // namespace aether::capture
