#include <aether/reconstruction/StableTextureAtlas.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace aether::reconstruction {

Result<StableTextureAtlasLayout> StableTextureAtlasLayout::create(StableTextureAtlasConfig config) {
    if (config.atlasSize == 0 || config.slotCapacity == 0 || config.maximumAtlasPixels == 0 ||
        config.atlasSize > config.maximumAtlasPixels / config.atlasSize ||
        config.gutterPixels > config.atlasSize / 4) {
        return fail(ErrorCode::invalidArgument, "Stable texture atlas configuration is invalid");
    }

    const double root = std::sqrt(static_cast<double>(config.slotCapacity));
    if (!std::isfinite(root) ||
        root > static_cast<double>(std::numeric_limits<std::size_t>::max())) {
        return fail(ErrorCode::resourceExhausted,
                    "Stable texture atlas slot capacity is too large");
    }

    const std::size_t columns = static_cast<std::size_t>(std::ceil(root));
    const std::size_t rows = (config.slotCapacity + columns - 1) / columns;
    const std::size_t cell = std::min(config.atlasSize / columns, config.atlasSize / rows);

    if (cell <= config.gutterPixels * 2 + 1) {
        return fail(ErrorCode::resourceExhausted,
                    "Stable texture atlas cannot allocate configured slots with gutters");
    }
    const std::size_t inner = cell - config.gutterPixels * 2;
    return StableTextureAtlasLayout(config, columns, rows, cell, inner);
}

Result<StableTextureAtlasTile> StableTextureAtlasLayout::tile(std::size_t slot) const {
    if (slot >= config_.slotCapacity) {
        return fail(ErrorCode::invalidArgument,
                    "Stable texture atlas slot is out of configured range");
    }

    const std::size_t column = slot % columns_;
    const std::size_t row = slot / columns_;
    const std::size_t tileX = column * cellPixels_ + config_.gutterPixels;
    const std::size_t tileY = row * cellPixels_ + config_.gutterPixels;

    const float atlas = static_cast<float>(config_.atlasSize);
    const float x0 = static_cast<float>(tileX) / atlas;
    const float y0 = static_cast<float>(tileY) / atlas;
    const float x1 = static_cast<float>(tileX + innerPixels_ - 1) / atlas;
    const float y1 = static_cast<float>(tileY + innerPixels_ - 1) / atlas;

    return StableTextureAtlasTile{
        .slot = slot,
        .column = column,
        .row = row,
        .cellPixels = cellPixels_,
        .innerPixels = innerPixels_,
        .uv = {simd_float2{x0, y0}, simd_float2{x1, y0}, simd_float2{x0, y1}},
    };
}

} // namespace aether::reconstruction
