#pragma once

#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace aether::gaussian {

/// Canonical, lossless representation of one standard 3DGS PLY vertex.
/// Rotation is normalized and uses GraphDECO's `(w, x, y, z)` property order. Scale and opacity
/// remain in their trained log/logit domains so importing never bakes an irreversible transform.
struct Gaussian final {
    std::array<float, 3> position{};
    std::array<float, 3> logScale{};
    std::array<float, 4> rotation{1.0F, 0.0F, 0.0F, 0.0F};
    float opacityLogit{};
    std::array<float, 3> dc{};
    std::array<float, 45> rest{};
    std::size_t restCount{};
};

struct GaussianAsset final {
    std::string name;
    std::vector<Gaussian> gaussians;
    std::size_t sphericalHarmonicDegree{};
    std::vector<std::string> diagnostics;
};

} // namespace aether::gaussian
