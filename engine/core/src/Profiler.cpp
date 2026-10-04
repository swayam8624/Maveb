#include <aether/core/Profiler.hpp>

namespace aether {

Profiler& Profiler::instance() {
    static Profiler profiler;
    return profiler;
}

void Profiler::record(std::string_view name, double milliseconds) {
    std::scoped_lock lock(mutex_);
    events_.push_back(ProfileEvent{std::string(name), milliseconds});
}

std::vector<ProfileEvent> Profiler::snapshotAndReset() {
    std::scoped_lock lock(mutex_);
    std::vector<ProfileEvent> result;
    result.swap(events_);
    return result;
}

ProfileScope::~ProfileScope() {
    Profiler::instance().record(name_, Clock::secondsBetween(start_, Clock::now()) * 1000.0);
}
} // namespace aether
