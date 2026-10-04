#include <aether/package/Sha256.hpp>

#include <algorithm>

namespace aether::package {
namespace {

constexpr std::array<std::uint32_t, 64> constants{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
    0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
    0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
    0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
    0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
    0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
    0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
    0xc67178f2U};

constexpr std::uint32_t rotateRight(std::uint32_t value, std::uint32_t amount) {
    return (value >> amount) | (value << (32U - amount));
}

std::uint32_t readBigEndian(const std::byte* bytes) {
    return (std::to_integer<std::uint32_t>(bytes[0]) << 24U) |
           (std::to_integer<std::uint32_t>(bytes[1]) << 16U) |
           (std::to_integer<std::uint32_t>(bytes[2]) << 8U) |
           std::to_integer<std::uint32_t>(bytes[3]);
}

} // namespace

Sha256::Sha256()
    : state_{0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
             0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U} {}

void Sha256::update(std::span<const std::byte> bytes) noexcept {
    if (finalized_ || bytes.empty())
        return;
    totalBytes_ += bytes.size();
    while (!bytes.empty()) {
        const std::size_t amount = std::min(buffer_.size() - buffered_, bytes.size());
        std::copy_n(bytes.begin(), amount,
                    buffer_.begin() + static_cast<std::ptrdiff_t>(buffered_));
        buffered_ += amount;
        bytes = bytes.subspan(amount);
        if (buffered_ == buffer_.size()) {
            processBlock(buffer_.data());
            buffered_ = 0;
        }
    }
}

Sha256Digest Sha256::finalize() noexcept {
    if (!finalized_) {
        const std::uint64_t bitCount = totalBytes_ * 8U;
        buffer_[buffered_++] = std::byte{0x80};
        if (buffered_ > 56) {
            std::fill(buffer_.begin() + static_cast<std::ptrdiff_t>(buffered_), buffer_.end(),
                      std::byte{0});
            processBlock(buffer_.data());
            buffered_ = 0;
        }
        std::fill(buffer_.begin() + static_cast<std::ptrdiff_t>(buffered_), buffer_.begin() + 56,
                  std::byte{0});
        for (std::size_t index = 0; index < 8; ++index) {
            buffer_[56 + index] = static_cast<std::byte>((bitCount >> ((7U - index) * 8U)) & 0xffU);
        }
        processBlock(buffer_.data());
        finalized_ = true;
    }

    Sha256Digest digest{};
    for (std::size_t word = 0; word < state_.size(); ++word) {
        for (std::size_t byte = 0; byte < 4; ++byte) {
            digest[word * 4 + byte] =
                static_cast<std::byte>((state_[word] >> ((3U - byte) * 8U)) & 0xffU);
        }
    }
    return digest;
}

Sha256Digest Sha256::hash(std::span<const std::byte> bytes) noexcept {
    Sha256 hash;
    hash.update(bytes);
    return hash.finalize();
}

std::string Sha256::hex(const Sha256Digest& digest) {
    constexpr char digits[] = "0123456789abcdef";
    std::string result;
    result.resize(digest.size() * 2);
    for (std::size_t index = 0; index < digest.size(); ++index) {
        const auto value = std::to_integer<unsigned int>(digest[index]);
        result[index * 2] = digits[value >> 4U];
        result[index * 2 + 1] = digits[value & 0x0fU];
    }
    return result;
}

void Sha256::processBlock(const std::byte* block) noexcept {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t index = 0; index < 16; ++index) {
        words[index] = readBigEndian(block + index * 4);
    }
    for (std::size_t index = 16; index < words.size(); ++index) {
        const std::uint32_t s0 = rotateRight(words[index - 15], 7) ^
                                 rotateRight(words[index - 15], 18) ^ (words[index - 15] >> 3U);
        const std::uint32_t s1 = rotateRight(words[index - 2], 17) ^
                                 rotateRight(words[index - 2], 19) ^ (words[index - 2] >> 10U);
        words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }

    auto [a, b, c, d, e, f, g, h] = state_;
    for (std::size_t index = 0; index < words.size(); ++index) {
        const std::uint32_t sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const std::uint32_t choice = (e & f) ^ (~e & g);
        const std::uint32_t temporary1 = h + sum1 + choice + constants[index] + words[index];
        const std::uint32_t sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        const std::uint32_t temporary2 = sum0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary1;
        d = c;
        c = b;
        b = a;
        a = temporary1 + temporary2;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
}

} // namespace aether::package
