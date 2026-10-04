#pragma once

#include <aether/core/Error.hpp>

#include <simd/simd.h>

#include <array>
#include <cstddef>

namespace aether::reconstruction {

struct StableTextureAtlasConfig final {
    std::size_t atlasSize{4096};
    std::size_t gutterPixels{4};
    std::size_t slotCapacity{1};
    std::size_t maximumAtlasPixels{8192ULL * 8192ULL};
};

struct StableTextureAtlasTile final {
    std::size_t slot{};
    std::size_t column{};
    std::size_t row{};
    std::size_t cellPixels{};
    std::size_t innerPixels{};
    std::array<simd_float2, 3> uv{};
};

/// Fixed-capacity triangle-slot layout for update-stable texture addressing.
///
/// The atlas grid depends only on the configured slot capacity, never on the current active
/// triangle count or order. A persistent triangle/patch slot therefore keeps identical UVs across
/// unrelated insertions, removals, and reordering as long as the slot remains valid.
class StableTextureAtlasLayout final {
  public:
    [[nodiscard]] static Result<StableTextureAtlasLayout> create(StableTextureAtlasConfig config);

    [[nodiscard]] Result<StableTextureAtlasTile> tile(std::size_t slot) const;

    [[nodiscard]] std::size_t columns() const noexcept {
        return columns_;
    }
    [[nodiscard]] std::size_t rows() const noexcept {
        return rows_;
    }
    [[nodiscard]] std::size_t cellPixels() const noexcept {
        return cellPixels_;
    }
    [[nodiscard]] std::size_t innerPixels() const noexcept {
        return innerPixels_;
    }
    [[nodiscard]] std::size_t slotCapacity() const noexcept {
        return config_.slotCapacity;
    }

  private:
    StableTextureAtlasLayout(StableTextureAtlasConfig config, std::size_t columns, std::size_t rows,
                             std::size_t cellPixels, std::size_t innerPixels)
        : config_(config), columns_(columns), rows_(rows), cellPixels_(cellPixels),
          innerPixels_(innerPixels) {}

    StableTextureAtlasConfig config_;
    std::size_t columns_{};
    std::size_t rows_{};
    std::size_t cellPixels_{};
    std::size_t innerPixels_{};
};

} // namespace aether::reconstruction
