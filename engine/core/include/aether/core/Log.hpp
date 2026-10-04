#pragma once

#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

namespace aether {

enum class LogLevel { debug, info, warning, error };

struct LogRecord {
    std::uint64_t unixMilliseconds{};
    LogLevel level{};
    std::string message;
};

class Log final {
  public:
    using Sink = std::function<void(LogLevel, std::string_view)>;

    static Log& instance();
    void setSink(Sink sink);
    void write(LogLevel level, std::string_view message) const;
    [[nodiscard]] std::vector<LogRecord> snapshot() const;

  private:
    Log();
    mutable std::mutex mutex_;
    Sink sink_;
    mutable std::deque<LogRecord> records_;
    static constexpr std::size_t maximumRecords_ = 4096;
};

} // namespace aether
