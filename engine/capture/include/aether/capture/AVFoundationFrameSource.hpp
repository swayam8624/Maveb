#pragma once

#include <aether/capture/FrameSource.hpp>
#include <memory>

namespace aether::capture {

class AVFoundationFrameSource final : public FrameSource {
public:
    AVFoundationFrameSource();
    ~AVFoundationFrameSource() override;

    Result<FrameSourceInfo> start() override;
    Result<void> stop() override;

    void setPacketCallback(PacketCallback callback) override;
    void setErrorCallback(ErrorCallback callback) override;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace aether::capture
