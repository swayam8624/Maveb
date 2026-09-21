#include <aether/reconstruction/PersistentTexturePageAllocator.hpp>

#include <algorithm>
#include <limits>
#include <unordered_set>

namespace aether::reconstruction {

Result<PersistentTexturePageAllocator>
PersistentTexturePageAllocator::create(PersistentTexturePageConfig config) {
    if (config.slotsPerPage == 0 || config.maximumPages == 0 ||
        config.slotsPerPage > std::numeric_limits<std::uint32_t>::max() ||
        config.maximumPages > std::numeric_limits<std::uint32_t>::max()) {
        return fail(ErrorCode::invalidArgument,
                    "Persistent texture page allocator configuration is invalid");
    }
    return PersistentTexturePageAllocator(config);
}

Result<std::uint32_t> PersistentTexturePageAllocator::createPage(std::uint64_t localityKey) {
    if (pages_.size() >= config_.maximumPages)
        return fail(ErrorCode::resourceExhausted,
                    "Persistent texture page allocator exhausted configured pages");
    const auto pageId = static_cast<std::uint32_t>(pages_.size());
    Page page;
    page.localityKey = localityKey;
    page.slots.resize(config_.slotsPerPage);
    pages_.push_back(std::move(page));
    localityPages_[localityKey].push_back(pageId);
    return pageId;
}

Result<PersistentTexturePageAddress>
PersistentTexturePageAllocator::allocate(std::uint64_t patchId, std::uint64_t localityKey) {
    if (patchId == 0)
        return fail(ErrorCode::invalidArgument, "Persistent texture patch ID cannot be zero");

    if (const auto existing = entries_.find(patchId); existing != entries_.end()) {
        if (existing->second.localityKey != localityKey)
            return fail(ErrorCode::invalidArgument,
                        "Persistent texture patch cannot silently change locality key");
        return existing->second.address;
    }

    auto& candidates = localityPages_[localityKey];
    std::uint32_t pageId{};
    std::size_t slotIndex = config_.slotsPerPage;
    bool found = false;
    for (const std::uint32_t candidate : candidates) {
        Page& page = pages_[candidate];
        for (std::size_t slot = 0; slot < page.slots.size(); ++slot) {
            if (!page.slots[slot].occupied) {
                pageId = candidate;
                slotIndex = slot;
                found = true;
                break;
            }
        }
        if (found)
            break;
    }

    if (!found) {
        auto created = createPage(localityKey);
        if (!created)
            return std::unexpected(created.error());
        pageId = *created;
        slotIndex = 0;
    }

    Page& page = pages_[pageId];
    page.slots[slotIndex] = Slot{.patchId = patchId, .occupied = true};
    PersistentTexturePageAddress result{
        .page = pageId,
        .slot = static_cast<std::uint32_t>(slotIndex),
    };
    entries_.emplace(patchId, Entry{.address = result, .localityKey = localityKey});
    return result;
}

Result<void> PersistentTexturePageAllocator::release(std::uint64_t patchId) {
    const auto entry = entries_.find(patchId);
    if (entry == entries_.end())
        return fail(ErrorCode::notFound, "Persistent texture patch was not allocated");

    const auto location = entry->second.address;
    if (location.page >= pages_.size() || location.slot >= pages_[location.page].slots.size()) {
        return fail(ErrorCode::corruptData,
                    "Persistent texture allocator entry points outside backing storage");
    }
    Slot& slot = pages_[location.page].slots[location.slot];
    if (!slot.occupied || slot.patchId != patchId)
        return fail(ErrorCode::corruptData,
                    "Persistent texture allocator slot ownership is inconsistent");
    slot = {};
    entries_.erase(entry);
    return {};
}

Result<PersistentTexturePageAddress>
PersistentTexturePageAllocator::address(std::uint64_t patchId) const {
    const auto entry = entries_.find(patchId);
    if (entry == entries_.end())
        return fail(ErrorCode::notFound, "Persistent texture patch was not allocated");
    return entry->second.address;
}

std::vector<std::uint32_t>
PersistentTexturePageAllocator::dirtyPages(const std::vector<std::uint64_t>& patchIds) const {
    std::vector<std::uint32_t> pages;
    pages.reserve(patchIds.size());
    for (const std::uint64_t patchId : patchIds) {
        const auto entry = entries_.find(patchId);
        if (entry != entries_.end())
            pages.push_back(entry->second.address.page);
    }
    std::sort(pages.begin(), pages.end());
    pages.erase(std::unique(pages.begin(), pages.end()), pages.end());
    return pages;
}

PersistentTexturePageStatistics PersistentTexturePageAllocator::statistics() const noexcept {
    const std::size_t capacity = pages_.size() * config_.slotsPerPage;
    const std::size_t active = entries_.size();
    const std::size_t free = capacity >= active ? capacity - active : 0;
    return {
        .pageCount = pages_.size(),
        .activeSlots = active,
        .freeSlots = free,
        .fragmentation =
            capacity == 0 ? 0.0 : static_cast<double>(free) / static_cast<double>(capacity),
    };
}

} // namespace aether::reconstruction
