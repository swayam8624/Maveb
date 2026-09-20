#pragma once

#include <aether/core/Error.hpp>

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace aether::gaussian {

struct GaussianPublicationRange final {
    std::uint32_t firstIndex{};
    std::uint32_t count{};
};

struct GaussianPublicationPlan final {
    std::vector<GaussianPublicationRange> ranges;
    std::size_t touchedRecords{};
    std::size_t touchedBytes{};
    std::size_t fullBufferBytes{};

    [[nodiscard]] double byteRatio() const noexcept {
        if (fullBufferBytes == 0)
            return 0.0;
        return static_cast<double>(touchedBytes) / static_cast<double>(fullBufferBytes);
    }
};

/// Coalesces a unique source-order subset into minimal contiguous publication ranges.
///
/// Input indices may be unsorted. Duplicate or out-of-range IDs fail closed because both would make
/// byte-accounting ambiguous. recordBytes is the actual GPU record stride, not canonical asset size.
[[nodiscard]] Result<GaussianPublicationPlan>
planGaussianPublication(std::span<const std::uint32_t> indices, std::size_t recordCount,
                        std::size_t recordBytes);

} // namespace aether::gaussian
