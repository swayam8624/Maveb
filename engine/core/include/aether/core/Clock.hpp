#pragma once

#include <chrono>

namespace aether {

class Clock final {
  public:
    using TimePoint = std::chrono::steady_clock::time_point;

    [[nodiscard]] static TimePoint now() noexcept {
        return std::chrono::steady_clock::now();
    }

    [[nodiscard]] static double secondsBetween(TimePoint begin, TimePoint end) noexcept {
        return std::chrono::duration<double>(end - begin).count();
    }
};

} // namespace aether
