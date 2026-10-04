#pragma once

#include <aether/core/Error.hpp>
#include <aether/metal/MetalPtr.hpp>

#include <Metal/Metal.hpp>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

namespace aether::metal {

struct BufferSlice {
    MTL::Buffer* buffer{};
    std::size_t offset{};
    std::size_t size{};
    std::byte* cpuAddress{};
};

class FrameContext final {
  public:
    static Result<std::unique_ptr<FrameContext>> create(MTL::Device* device, std::uint32_t index);

    FrameContext(const FrameContext&) = delete;
    FrameContext& operator=(const FrameContext&) = delete;

    void beginFrame();
    [[nodiscard]] Result<BufferSlice> allocateUpload(std::size_t size, std::size_t alignment = 256);
    [[nodiscard]] Result<BufferSlice> allocateReadback(std::size_t size,
                                                       std::size_t alignment = 256);
    void deferUntilReusable(std::function<void()> cleanup);

    [[nodiscard]] std::uint32_t index() const noexcept {
        return index_;
    }
    [[nodiscard]] MTL::Heap* transientHeap() const noexcept {
        return transientHeap_.get();
    }
    [[nodiscard]] std::size_t uploadCapacity() const noexcept;
    [[nodiscard]] std::size_t readbackCapacity() const noexcept;

  private:
    FrameContext(std::uint32_t index, MetalPtr<MTL::Buffer> upload, MetalPtr<MTL::Buffer> readback,
                 MetalPtr<MTL::Heap> transientHeap);
    [[nodiscard]] Result<BufferSlice> allocate(MTL::Buffer* buffer, std::size_t& cursor,
                                               std::size_t size, std::size_t alignment,
                                               const char* purpose);

    std::uint32_t index_{};
    MetalPtr<MTL::Buffer> upload_;
    MetalPtr<MTL::Buffer> readback_;
    MetalPtr<MTL::Heap> transientHeap_;
    std::size_t uploadCursor_{};
    std::size_t readbackCursor_{};
    std::vector<std::function<void()>> deferredCleanup_;
};

} // namespace aether::metal
