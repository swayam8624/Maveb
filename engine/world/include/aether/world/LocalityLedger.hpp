#pragma once

#include <aether/core/Error.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace aether::world {

/// Work domains used by the MAVEB Update Locality Ratio (ULR) evidence contract.
///
/// Domains are deliberately not combined into one scalar because their units are not comparable.
/// A TSDF block, a Gaussian primitive inspection, a texture texel, and a transferred byte are
/// different physical/computational quantities. Each domain therefore keeps an independent
/// incremental/full-rebuild counter and ratio.
enum class LocalityDomain : std::uint8_t {
    observationsInspected = 0,
    tsdfBlocksRead,
    tsdfBlocksWritten,
    tsdfBytesReadBack,
    meshCellsRegenerated,
    meshPatchesRegenerated,
    gaussiansInspected,
    gaussiansUpdated,
    texturePagesUpdated,
    textureSlotsConsidered,
    textureTexelsWritten,
    materialStatesUpdated,
    cpuToGpuBytes,
    gpuToCpuBytes,
    gpuPublicationBytes,
    temporalPixelsInvalidated,
    archiveBytesWritten,
    count,
};

struct LocalityCounter final {
    std::uint64_t incremental{};
    std::uint64_t full{};

    [[nodiscard]] std::optional<double> ratio() const noexcept;
};

/// Per-revision work ledger for one incremental-vs-full comparison.
///
/// The full value must describe the equivalent reference transaction for the same scene/revision
/// and work domain. A domain with both values equal to zero is not applicable. Incremental work
/// with a zero full baseline is invalid and fails validation rather than producing infinity.
class LocalityLedger final {
  public:
    [[nodiscard]] Result<void> set(LocalityDomain domain, std::uint64_t incremental,
                                   std::uint64_t full);
    [[nodiscard]] Result<void> addIncremental(LocalityDomain domain, std::uint64_t amount);
    [[nodiscard]] Result<void> addFull(LocalityDomain domain, std::uint64_t amount);

    [[nodiscard]] const LocalityCounter& counter(LocalityDomain domain) const noexcept;
    [[nodiscard]] Result<void> validate() const;

    /// Strong S1 certificate gate: requires a non-zero equivalent full baseline for every core
    /// heterogeneous layer used by the headline dependency-locality claim.
    [[nodiscard]] Result<void> validateS1CoreCoverage() const;

    /// Deterministic JSON object containing raw counters and per-domain ratio/null.
    /// The caller owns experiment metadata such as git SHA, dataset, machine, and timing.
    [[nodiscard]] Result<std::string> toJson() const;

  private:
    [[nodiscard]] static Result<std::size_t> checkedIndex(LocalityDomain domain);
    std::array<LocalityCounter, static_cast<std::size_t>(LocalityDomain::count)> counters_{};
};

[[nodiscard]] std::string_view localityDomainName(LocalityDomain domain) noexcept;

} // namespace aether::world
