#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>

#include <array>
#include <cstddef>
#include <vector>

namespace aether::reconstruction {

struct GeometryMetrics final {
    double accuracyMeanMetres{};
    double completenessMeanMetres{};
    double chamferMeanMetres{};
    double fScore{};
    std::size_t evaluatedVertices{};
    std::size_t referencePoints{};
    std::size_t degenerateTriangles{};
    std::size_t invalidIndices{};

    [[nodiscard]] bool manifoldInputValid() const noexcept {
        return invalidIndices == 0 && degenerateTriangles == 0;
    }
};

Result<GeometryMetrics>
evaluateGeometry(const mesh::MeshAsset& prediction,
                 const std::vector<std::array<double, 3>>& referencePoints,
                 double fScoreThresholdMetres);

} // namespace aether::reconstruction
