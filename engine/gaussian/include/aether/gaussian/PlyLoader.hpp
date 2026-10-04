#pragma once

#include <aether/core/Error.hpp>
#include <aether/gaussian/GaussianAsset.hpp>

#include <cstddef>
#include <cstdint>
#include <filesystem>

namespace aether::gaussian {

struct PlyLimits final {
    std::uintmax_t maximumFileBytes{16ULL * 1024ULL * 1024ULL * 1024ULL};
    std::size_t maximumHeaderBytes{1ULL * 1024ULL * 1024ULL};
    std::size_t maximumProperties{256};
    std::size_t maximumGaussians{100'000'000};
    float maximumAbsoluteLogScale{30.0F};
};

class PlyLoader final {
  public:
    /// Input: an ASCII or binary-little-endian standard 3DGS PLY and explicit allocation limits.
    /// Output: validated canonical Gaussians plus non-fatal conversion diagnostics.
    /// Task: reject malformed/hostile inputs before any renderer or GPU allocation sees them.
    [[nodiscard]] static Result<GaussianAsset> load(const std::filesystem::path& path,
                                                    const PlyLimits& limits = {});
};

} // namespace aether::gaussian
