#pragma once

#include <aether/core/Error.hpp>

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace aether {

enum class JobStatus { queued, running, succeeded, failed, cancelled };

namespace detail {
struct JobState;
}

class JobContext final {
  public:
    [[nodiscard]] bool isCancellationRequested() const noexcept;
    void setProgress(double progress) noexcept;

  private:
    friend class JobSystem;
    explicit JobContext(std::shared_ptr<detail::JobState> state) : state_(std::move(state)) {}
    std::shared_ptr<detail::JobState> state_;
};

class JobHandle final {
  public:
    JobHandle() = default;

    [[nodiscard]] bool valid() const noexcept {
        return state_ != nullptr;
    }
    [[nodiscard]] std::uint64_t id() const noexcept;
    [[nodiscard]] std::string name() const;
    [[nodiscard]] JobStatus status() const noexcept;
    [[nodiscard]] double progress() const noexcept;
    [[nodiscard]] std::optional<Error> error() const;

    void cancel() const noexcept;
    void wait() const;

  private:
    friend class JobSystem;
    explicit JobHandle(std::shared_ptr<detail::JobState> state) : state_(std::move(state)) {}
    std::shared_ptr<detail::JobState> state_;
};

class JobSystem final {
  public:
    using Task = std::function<Result<void>(JobContext&)>;

    explicit JobSystem(std::size_t workerCount = defaultWorkerCount());
    ~JobSystem();

    JobSystem(const JobSystem&) = delete;
    JobSystem& operator=(const JobSystem&) = delete;

    [[nodiscard]] JobHandle submit(std::string name, Task task);
    [[nodiscard]] static std::size_t defaultWorkerCount() noexcept;

  private:
    struct QueuedJob {
        std::shared_ptr<detail::JobState> state;
        Task task;
    };

    void workerMain();

    std::atomic<std::uint64_t> nextId_{1};
    std::mutex queueMutex_;
    std::condition_variable queueCondition_;
    std::deque<QueuedJob> queue_;
    bool stopping_{};
    std::vector<std::thread> workers_;
};

} // namespace aether
