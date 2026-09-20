#pragma once

#include <aether/core/Error.hpp>

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace aether::reconstruction {

struct PersistentTexturePageConfig final {
    std::size_t slotsPerPage{64};
    std::size_t maximumPages{65'536};
};

struct PersistentTexturePageAddress final {
    std::uint32_t page{};
    std::uint32_t slot{};

    friend bool operator==(const PersistentTexturePageAddress&,
                           const PersistentTexturePageAddress&) = default;
};

struct PersistentTexturePageStatistics final {
    std::size_t pageCount{};
    std::size_t activeSlots{};
    std::size_t freeSlots{};
    double fragmentation{};
};

/// Stable page allocator for persistent reconstructed texture patches.
///
/// Patches sharing the same dependency/locality key are preferentially packed into the same pages.
/// Releasing a patch creates a hole that can be reused by a later patch with the same locality key;
/// unrelated existing addresses never move. Empty pages are deliberately retained so stable page
/// IDs are not renumbered by unrelated deletion.
class PersistentTexturePageAllocator final {
  public:
    [[nodiscard]] static Result<PersistentTexturePageAllocator>
    create(PersistentTexturePageConfig config);

    [[nodiscard]] Result<PersistentTexturePageAddress>
    allocate(std::uint64_t patchId, std::uint64_t localityKey);

    [[nodiscard]] Result<void> release(std::uint64_t patchId);

    [[nodiscard]] Result<PersistentTexturePageAddress> address(std::uint64_t patchId) const;

    [[nodiscard]] std::vector<std::uint32_t>
    dirtyPages(const std::vector<std::uint64_t>& patchIds) const;

    [[nodiscard]] PersistentTexturePageStatistics statistics() const noexcept;

  private:
    struct Slot final {
        std::uint64_t patchId{};
        bool occupied{};
    };
    struct Page final {
        std::uint64_t localityKey{};
        std::vector<Slot> slots;
    };
    struct Entry final {
        PersistentTexturePageAddress address;
        std::uint64_t localityKey{};
    };

    explicit PersistentTexturePageAllocator(PersistentTexturePageConfig config)
        : config_(config) {}

    [[nodiscard]] Result<std::uint32_t> createPage(std::uint64_t localityKey);

    PersistentTexturePageConfig config_;
    std::vector<Page> pages_;
    std::unordered_map<std::uint64_t, Entry> entries_;
    std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> localityPages_;
};

} // namespace aether::reconstruction
