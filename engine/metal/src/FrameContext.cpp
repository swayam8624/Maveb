#include <aether/metal/FrameContext.hpp>

#include <Foundation/Foundation.hpp>

#include <limits>
#include <string>

namespace aether::metal {
namespace {
constexpr std::size_t uploadBytes = 8U * 1024U * 1024U;
constexpr std::size_t readbackBytes = 256U * 1024U;
constexpr std::size_t transientHeapBytes = 64U * 1024U * 1024U;

bool isPowerOfTwo(std::size_t value) {
    return value != 0 && (value & (value - 1U)) == 0;
}

std::size_t alignUp(std::size_t value, std::size_t alignment) {
    return (value + alignment - 1U) & ~(alignment - 1U);
}

void label(MTL::Resource* resource, const std::string& name) {
    resource->setLabel(NS::String::string(name.c_str(), NS::UTF8StringEncoding));
}
} // namespace

Result<std::unique_ptr<FrameContext>> FrameContext::create(MTL::Device* device,
                                                           std::uint32_t index) {
    if (!device) {
        return fail(ErrorCode::metal, "Cannot create a frame context without a Metal device");
    }

    auto upload = adopt(device->newBuffer(uploadBytes, MTL::ResourceStorageModeShared));
    auto readback = adopt(device->newBuffer(readbackBytes, MTL::ResourceStorageModeShared));
    auto descriptor = adopt(MTL::HeapDescriptor::alloc()->init());
    descriptor->setSize(transientHeapBytes);
    descriptor->setStorageMode(MTL::StorageModePrivate);
    descriptor->setHazardTrackingMode(MTL::HazardTrackingModeTracked);
    auto heap = adopt(device->newHeap(descriptor.get()));
    if (!upload || !readback || !heap) {
        return fail(ErrorCode::resourceExhausted, "Metal failed to allocate frame resources",
                    "frame " + std::to_string(index));
    }

    label(upload.get(), "Frame " + std::to_string(index) + " Upload Ring");
    label(readback.get(), "Frame " + std::to_string(index) + " Readback Ring");
    const std::string heapName = "Frame " + std::to_string(index) + " Transient Heap";
    heap->setLabel(NS::String::string(heapName.c_str(), NS::UTF8StringEncoding));
    return std::unique_ptr<FrameContext>(
        new FrameContext(index, std::move(upload), std::move(readback), std::move(heap)));
}

FrameContext::FrameContext(std::uint32_t index, MetalPtr<MTL::Buffer> upload,
                           MetalPtr<MTL::Buffer> readback, MetalPtr<MTL::Heap> transientHeap)
    : index_(index), upload_(std::move(upload)), readback_(std::move(readback)),
      transientHeap_(std::move(transientHeap)) {}

void FrameContext::beginFrame() {
    for (auto& cleanup : deferredCleanup_) {
        cleanup();
    }
    deferredCleanup_.clear();
    uploadCursor_ = 0;
    readbackCursor_ = 0;
}

Result<BufferSlice> FrameContext::allocateUpload(std::size_t size, std::size_t alignment) {
    return allocate(upload_.get(), uploadCursor_, size, alignment, "upload");
}

Result<BufferSlice> FrameContext::allocateReadback(std::size_t size, std::size_t alignment) {
    return allocate(readback_.get(), readbackCursor_, size, alignment, "readback");
}

void FrameContext::deferUntilReusable(std::function<void()> cleanup) {
    deferredCleanup_.push_back(std::move(cleanup));
}

std::size_t FrameContext::uploadCapacity() const noexcept {
    return static_cast<std::size_t>(upload_->length());
}

std::size_t FrameContext::readbackCapacity() const noexcept {
    return static_cast<std::size_t>(readback_->length());
}

Result<BufferSlice> FrameContext::allocate(MTL::Buffer* buffer, std::size_t& cursor,
                                           std::size_t size, std::size_t alignment,
                                           const char* purpose) {
    if (size == 0 || !isPowerOfTwo(alignment)) {
        return fail(ErrorCode::invalidArgument,
                    "Ring allocation requires non-zero size and power-of-two alignment", purpose);
    }
    if (cursor > std::numeric_limits<std::size_t>::max() - alignment) {
        return fail(ErrorCode::resourceExhausted, "Ring allocation offset overflow", purpose);
    }
    const std::size_t offset = alignUp(cursor, alignment);
    const std::size_t capacity = static_cast<std::size_t>(buffer->length());
    if (offset > capacity || size > capacity - offset) {
        return fail(ErrorCode::resourceExhausted, "Per-frame ring capacity exceeded", purpose);
    }
    cursor = offset + size;
    auto* base = static_cast<std::byte*>(buffer->contents());
    return BufferSlice{buffer, offset, size, base ? base + offset : nullptr};
}

} // namespace aether::metal
