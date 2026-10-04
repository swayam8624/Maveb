#pragma once

#include <aether/reconstruction/ReconstructionContracts.hpp>

namespace aether::reconstruction {

class RecordedPoseProvider final : public IPoseProvider {
public:
    Result<PoseEstimate> estimate(const capture::CapturePacket& packet) override;
};

class RecordedRgbdDepthProvider final : public IDepthProvider {
public:
    Result<DepthObservation> estimate(const capture::CapturePacket& packet,
                                      const PoseEstimate& pose) override;
};

} // namespace aether::reconstruction
