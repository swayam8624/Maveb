#include <aether/reconstruction/RecordedProviders.hpp>

namespace aether::reconstruction {

Result<PoseEstimate> RecordedPoseProvider::estimate(const capture::CapturePacket& packet) {
    if (!packet.cameraToWorld)
        return fail(ErrorCode::notFound, "Recorded frame has no camera pose",
                    std::to_string(packet.frameId));
    return PoseEstimate{*packet.cameraToWorld, 1.0, 0, 0.0, true};
}

Result<DepthObservation>
RecordedRgbdDepthProvider::estimate(const capture::CapturePacket& packet,
                                   const PoseEstimate& pose) {
    if (!pose.metricScale)
        return fail(ErrorCode::invalidArgument,
                    "Recorded metric depth requires a metric-scale pose");
    if (!packet.hasMetricDepth())
        return fail(ErrorCode::notFound, "Recorded frame has no valid metric depth",
                    std::to_string(packet.frameId));
    return DepthObservation{*packet.depthMetres,
                            packet.depthConfidence ? &*packet.depthConfidence : nullptr,
                            1.0,
                            0.0,
                            "recorded-rgbd-v1"};
}

} // namespace aether::reconstruction
