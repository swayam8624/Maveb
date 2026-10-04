#pragma once

#include <cstddef>
#include <utility>

namespace aether::metal {

struct AdoptTag final {};
struct RetainTag final {};
inline constexpr AdoptTag adoptTag{};
inline constexpr RetainTag retainTag{};

template <typename T> class MetalPtr final {
  public:
    MetalPtr() = default;
    MetalPtr(std::nullptr_t) noexcept {}
    MetalPtr(T* pointer, AdoptTag) noexcept : pointer_(pointer) {}
    MetalPtr(T* pointer, RetainTag) noexcept : pointer_(pointer ? pointer->retain() : nullptr) {}

    MetalPtr(const MetalPtr& other) noexcept
        : pointer_(other.pointer_ ? other.pointer_->retain() : nullptr) {}
    MetalPtr(MetalPtr&& other) noexcept : pointer_(std::exchange(other.pointer_, nullptr)) {}

    ~MetalPtr() {
        reset();
    }

    MetalPtr& operator=(MetalPtr other) noexcept {
        swap(other);
        return *this;
    }

    void reset(T* pointer = nullptr, AdoptTag = adoptTag) noexcept {
        if (pointer_) {
            pointer_->release();
        }
        pointer_ = pointer;
    }

    void swap(MetalPtr& other) noexcept {
        std::swap(pointer_, other.pointer_);
    }
    [[nodiscard]] T* get() const noexcept {
        return pointer_;
    }
    [[nodiscard]] T* operator->() const noexcept {
        return pointer_;
    }
    [[nodiscard]] explicit operator bool() const noexcept {
        return pointer_ != nullptr;
    }

  private:
    T* pointer_{};
};

template <typename T> [[nodiscard]] MetalPtr<T> adopt(T* pointer) noexcept {
    return MetalPtr<T>(pointer, adoptTag);
}

template <typename T> [[nodiscard]] MetalPtr<T> retain(T* pointer) noexcept {
    return MetalPtr<T>(pointer, retainTag);
}

} // namespace aether::metal
