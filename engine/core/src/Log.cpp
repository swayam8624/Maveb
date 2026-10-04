#include <aether/core/Log.hpp>

#include <chrono>
#include <iostream>

namespace aether {
namespace {
const char* label(LogLevel level) {
    switch (level) {
    case LogLevel::debug:
        return "DEBUG";
    case LogLevel::info:
        return "INFO";
    case LogLevel::warning:
        return "WARN";
    case LogLevel::error:
        return "ERROR";
    }
    return "UNKNOWN";
}
} // namespace

Log& Log::instance() {
    static Log log;
    return log;
}

Log::Log()
    : sink_([](LogLevel level, std::string_view message) {
          std::clog << "[AETHER][" << label(level) << "] " << message << '\n';
      }) {}

void Log::setSink(Sink sink) {
    std::scoped_lock lock(mutex_);
    sink_ = std::move(sink);
}

void Log::write(LogLevel level, std::string_view message) const {
    Sink sink;
    {
        std::scoped_lock lock(mutex_);
        const auto now = std::chrono::time_point_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now());
        records_.push_back(LogRecord{static_cast<std::uint64_t>(now.time_since_epoch().count()),
                                     level, std::string(message)});
        if (records_.size() > maximumRecords_) {
            records_.pop_front();
        }
        sink = sink_;
    }
    sink(level, message);
}

std::vector<LogRecord> Log::snapshot() const {
    std::scoped_lock lock(mutex_);
    return {records_.begin(), records_.end()};
}
} // namespace aether
