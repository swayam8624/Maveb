#pragma once

#include <aether/capture/CapturePacket.hpp>
#include <aether/core/Error.hpp>

#include <functional>
#include <string>

namespace aether::capture {

struct FrameSourceInfo final {
    std::string sourceId;
    CaptureSourceKind sourceKind{CaptureSourceKind::camera};
    std::string displayName;
    bool providesDepth{};
    bool providesPose{};
    bool providesImu{};
};

class FrameSource {
public:
    virtual ~FrameSource() = default;

    virtual Result<FrameSourceInfo> start() = 0;
    virtual Result<void> stop() = 0;

    using PacketCallback = std::function<void(CapturePacket)>;
    using ErrorCallback = std::function<void(Error)>;

    virtual void setPacketCallback(PacketCallback callback) = 0;
    virtual void setErrorCallback(ErrorCallback callback) = 0;
};

} // namespace aether::capture
