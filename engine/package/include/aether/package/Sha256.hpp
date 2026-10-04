#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>

namespace aether::package {

using Sha256Digest = std::array<std::byte, 32>;

class Sha256 final {
  public:
    Sha256();
    void update(std::span<const std::byte> bytes) noexcept;
    [[nodiscard]] Sha256Digest finalize() noexcept;

    [[nodiscard]] static Sha256Digest hash(std::span<const std::byte> bytes) noexcept;
    [[nodiscard]] static std::string hex(const Sha256Digest& digest);

  private:
    void processBlock(const std::byte* block) noexcept;

    std::array<std::uint32_t, 8> state_{};
    std::array<std::byte, 64> buffer_{};
    std::size_t buffered_{};
    std::uint64_t totalBytes_{};
    bool finalized_{};
};

} // namespace aether::package
