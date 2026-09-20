#pragma once

#include <string_view>

namespace aether::cbrc {

inline constexpr std::string_view gaussianOutputGraphVersion =
    "gaussian-output-cone-v2";
inline constexpr std::string_view gaussianTemporalBoundVersion =
    "gaussian-image-temporal-v1";
inline constexpr std::string_view headlessTemporalPixelCostModelVersion =
    "temporal-pixel-work-v1";
inline constexpr std::string_view capturedWorldGraphVersion =
    "captured-world-heterogeneous-v1";

} // namespace aether::cbrc
