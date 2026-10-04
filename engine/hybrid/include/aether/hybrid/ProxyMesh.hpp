#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace aether::hybrid {

struct ProxyVertex final {
    std::array<float, 3> position{};
    std::array<float, 3> normal{};
    float confidence{1.0F};
    std::uint32_t colorRgba{0xffffffffU};
};

struct ProxyMesh final {
    std::vector<ProxyVertex> vertices;
    std::vector<std::uint32_t> indices;
};

} // namespace aether::hybrid
