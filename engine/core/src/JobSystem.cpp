// SOURCE STUDY NOTE:
// Execution infrastructure. The declared interface lives in
// engine/core/include/aether/core/JobSystem.hpp; higher-level scene/reconstruction work can schedule work
// here. Inspect job lifetime and synchronization before parallelizing expensive work.
// Follow docs/SOURCE_READING_ORDER.md for upstream/downstream files.

#include <aether/core/JobSystem.hpp>

#include <algorithm>
#include <utility>

namespace aether::detail {

struct JobState {
    std::uint64_t id{};
    std::string name;
    std::atomic<JobStatus> status{JobStatus::queued};
    std::atomic<double> progress{};
    std::atomic<bool> cancellationRequested{};
    mutable std::mutex resultMutex;
    std::condition_variable completed;
    std::optional<Error> error;
};

} // namespace aether::detail

namespace aether {

namespace {
bool terminal(JobStatus status) {
    return status == JobStatus::succeeded || status == JobStatus::failed ||
           status == JobStatus::cancelled;
}
} // namespace

// Cooperative cancellation check from a running task. JobHandle::cancel()
// only sets this flag; expensive work must poll it and return a cancelled
// Result so workerMain can publish a terminal state.
bool JobContext::isCancellationRequested() const noexcept {
    return state_->cancellationRequested.load(std::memory_order_relaxed);
}

// Publish bounded [0,1] progress for UI/diagnostics; JobHandle::progress()
// reads the atomic snapshot without taking the result mutex.
void JobContext::setProgress(double progress) noexcept {
    state_->progress.store(std::clamp(progress, 0.0, 1.0), std::memory_order_relaxed);
}

std::uint64_t JobHandle::id() const noexcept {
    return state_ ? state_->id : 0;
}

std::string JobHandle::name() const {
    return state_ ? state_->name : std::string{};
}

JobStatus JobHandle::status() const noexcept {
    return state_ ? state_->status.load(std::memory_order_acquire) : JobStatus::cancelled;
}

double JobHandle::progress() const noexcept {
    return state_ ? state_->progress.load(std::memory_order_relaxed) : 0.0;
}

std::optional<Error> JobHandle::error() const {
    if (!state_) {
        return Error{ErrorCode::invalidArgument, "Invalid job handle", {}};
    }
    std::scoped_lock lock(state_->resultMutex);
    return state_->error;
}

// Request cancellation, not immediate preemption. A queued job is skipped;
// an already-running callback must check its JobContext cooperatively.
void JobHandle::cancel() const noexcept {
    if (state_) {
        state_->cancellationRequested.store(true, std::memory_order_release);
    }
}

// Wait on the terminal-state condition variable, not simply until a worker
// dequeues the task. Call error() afterwards to distinguish failed work
// from a successful or cancelled job.
void JobHandle::wait() const {
    if (!state_) {
        return;
    }
    std::unique_lock lock(state_->resultMutex);
    state_->completed.wait(
        lock, [&] { return terminal(state_->status.load(std::memory_order_acquire)); });
}

JobSystem::JobSystem(std::size_t workerCount) {
    workerCount = std::max<std::size_t>(1, workerCount);
    workers_.reserve(workerCount);
    for (std::size_t index = 0; index < workerCount; ++index) {
        workers_.emplace_back([this] { workerMain(); });
    }
}

JobSystem::~JobSystem() {
    {
        std::scoped_lock lock(queueMutex_);
        stopping_ = true;
        for (auto& job : queue_) {
            job.state->cancellationRequested.store(true, std::memory_order_release);
        }
    }
    queueCondition_.notify_all();
    for (auto& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

// Give each task a reference-counted JobState and a monotonically assigned
// ID. The queue owns the callable; the returned handle observes state
// without owning the JobSystem. Submissions during teardown are cancelled.
JobHandle JobSystem::submit(std::string name, Task task) {
    auto state = std::make_shared<detail::JobState>();
    state->id = nextId_.fetch_add(1, std::memory_order_relaxed);
    state->name = std::move(name);
    {
        std::scoped_lock lock(queueMutex_);
        if (stopping_) {
            state->status.store(JobStatus::cancelled, std::memory_order_release);
            state->error = Error{ErrorCode::cancelled, "Job system is shutting down", state->name};
            state->completed.notify_all();
            return JobHandle(state);
        }
        queue_.push_back(QueuedJob{state, std::move(task)});
    }
    queueCondition_.notify_one();
    return JobHandle(state);
}

std::size_t JobSystem::defaultWorkerCount() noexcept {
    const std::size_t hardware = std::thread::hardware_concurrency();
    return hardware > 1 ? hardware - 1 : 1;
}

// Worker state machine: wait -> dequeue -> skip cancelled jobs -> run Task
// with JobContext -> publish success/failure/cancellation -> notify waiter.
// Tasks should report failure using Result<void>; uncaught exceptions are
// not translated to Result in this worker implementation.
void JobSystem::workerMain() {
    while (true) {
        QueuedJob job;
        {
            std::unique_lock lock(queueMutex_);
            queueCondition_.wait(lock, [&] { return stopping_ || !queue_.empty(); });
            if (stopping_ && queue_.empty()) {
                return;
            }
            job = std::move(queue_.front());
            queue_.pop_front();
        }

        if (job.state->cancellationRequested.load(std::memory_order_acquire)) {
            job.state->status.store(JobStatus::cancelled, std::memory_order_release);
            job.state->completed.notify_all();
            continue;
        }

        job.state->status.store(JobStatus::running, std::memory_order_release);
        JobContext context(job.state);
        Result<void> result = job.task(context);
        {
            std::scoped_lock lock(job.state->resultMutex);
            if (job.state->cancellationRequested.load(std::memory_order_acquire) ||
                (!result && result.error().code == ErrorCode::cancelled)) {
                job.state->status.store(JobStatus::cancelled, std::memory_order_release);
                if (!result) {
                    job.state->error = result.error();
                }
            } else if (!result) {
                job.state->error = result.error();
                job.state->status.store(JobStatus::failed, std::memory_order_release);
            } else {
                job.state->progress.store(1.0, std::memory_order_relaxed);
                job.state->status.store(JobStatus::succeeded, std::memory_order_release);
            }
        }
        job.state->completed.notify_all();
    }
}

} // namespace aether
