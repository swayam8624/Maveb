#pragma once

#include <aether/capture/FrameSource.hpp>

#include <filesystem>
#include <memory>
#include <optional>

namespace aether::capture {

struct RecordedPlaybackConfig final {
    std::optional<std::size_t> injectedFailureFrame;
};

/// Deterministic reader for unpacked AETHER capture schema v1 directories.
class RecordedSequenceSource final : public FrameSource {
public:
    static Result<std::unique_ptr<RecordedSequenceSource>>
    open(const std::filesystem::path& directory, RecordedPlaybackConfig config = {});

    ~RecordedSequenceSource() override;

    Result<FrameSourceInfo> start() override;
    Result<void> stop() override;
    void setPacketCallback(PacketCallback callback) override;
    void setErrorCallback(ErrorCallback callback) override;

    /// Emits exactly one packet. Returns false at end of sequence.
    Result<bool> step();
    void rewind() noexcept;
    [[nodiscard]] std::size_t frameCount() const noexcept;
    [[nodiscard]] std::size_t position() const noexcept;

private:
    class Impl;
    explicit RecordedSequenceSource(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> impl_;
};

} // namespace aether::capture
