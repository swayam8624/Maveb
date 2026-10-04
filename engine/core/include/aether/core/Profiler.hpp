#pragma once

#include <aether/core/Clock.hpp>

#include <mutex>
#include <string>
#include <string_view>
#include <vector>

namespace aether {

struct ProfileEvent {
    std::string name;
    double milliseconds{};
};

class Profiler final {
  public:
    static Profiler& instance();
    void record(std::string_view name, double milliseconds);
    [[nodiscard]] std::vector<ProfileEvent> snapshotAndReset();

  private:
    std::mutex mutex_;
    std::vector<ProfileEvent> events_;
};

class ProfileScope final {
  public:
    explicit ProfileScope(std::string_view name) : name_(name), start_(Clock::now()) {}
    ~ProfileScope();
    ProfileScope(const ProfileScope&) = delete;
    ProfileScope& operator=(const ProfileScope&) = delete;

  private:
    std::string name_;
    Clock::TimePoint start_;
};

} // namespace aether
