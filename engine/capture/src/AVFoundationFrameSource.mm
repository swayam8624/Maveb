#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>

#include <aether/capture/AVFoundationFrameSource.hpp>

#include <atomic>
#include <chrono>
#include <mutex>
#include <utility>

namespace {

std::uint64_t nanoseconds(CMTime time) {
    if (!CMTIME_IS_NUMERIC(time) || time.timescale <= 0)
        return 0;
    const long double seconds =
        static_cast<long double>(time.value) / static_cast<long double>(time.timescale);
    return static_cast<std::uint64_t>(seconds * 1'000'000'000.0L);
}

std::uint64_t hostNanoseconds() {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

} // namespace

@interface AetherCaptureDelegate : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
- (void)setPacketCallback:(aether::capture::FrameSource::PacketCallback)callback
                 sourceId:(std::string)sourceId;
@end

@implementation AetherCaptureDelegate {
    aether::capture::FrameSource::PacketCallback _packetCallback;
    std::string _sourceId;
    std::mutex _mutex;
    std::atomic<std::uint64_t> _nextFrameId;
}

- (instancetype)init {
    self = [super init];
    if (self)
        _nextFrameId.store(1);
    return self;
}

- (void)setPacketCallback:(aether::capture::FrameSource::PacketCallback)callback
                 sourceId:(std::string)sourceId {
    std::lock_guard lock(_mutex);
    _packetCallback = std::move(callback);
    _sourceId = std::move(sourceId);
}

- (void)captureOutput:(AVCaptureOutput*)output
    didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
       fromConnection:(AVCaptureConnection*)connection {
    (void)output;
    CVPixelBufferRef pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (!pixelBuffer)
        return;

    if (CVPixelBufferLockBaseAddress(pixelBuffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess)
        return;
    CFRetain(pixelBuffer);
    std::shared_ptr<const void> owner(pixelBuffer, [](const void* pointer) {
        auto buffer = const_cast<CVPixelBufferRef>(
            static_cast<const __CVBuffer*>(pointer));
        CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
        CFRelease(buffer);
    });

    const auto width = static_cast<std::uint32_t>(CVPixelBufferGetWidth(pixelBuffer));
    const auto height = static_cast<std::uint32_t>(CVPixelBufferGetHeight(pixelBuffer));
    const auto stride = static_cast<std::uint32_t>(CVPixelBufferGetBytesPerRow(pixelBuffer));
    auto* base = static_cast<const std::byte*>(CVPixelBufferGetBaseAddress(pixelBuffer));
    if (!base) {
        owner.reset();
        return;
    }

    aether::capture::FrameSource::PacketCallback callback;
    std::string sourceId;
    {
        std::lock_guard lock(_mutex);
        callback = _packetCallback;
        sourceId = _sourceId;
    }
    if (!callback)
        return;

    aether::capture::CapturePacket packet;
    packet.frameId = _nextFrameId.fetch_add(1);
    packet.sourceId = std::move(sourceId);
    packet.sourceKind = aether::capture::CaptureSourceKind::camera;
    packet.presentationTimestampNs =
        nanoseconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer));
    packet.hostTimestampNs = hostNanoseconds();
    packet.mirrored = connection.videoMirrored;
    packet.calibration.width = width;
    packet.calibration.height = height;
    packet.colorPlanes.push_back(aether::capture::ImagePlane{
        aether::capture::BufferView{
            std::move(owner), base, static_cast<std::size_t>(stride) * height},
        aether::capture::PixelFormat::bgra8,
        width,
        height,
        stride,
    });
    callback(std::move(packet));
}

@end

namespace aether::capture {

class AVFoundationFrameSource::Impl final {
public:
    Impl()
        : delegate_([[AetherCaptureDelegate alloc] init]),
          session_([[AVCaptureSession alloc] init]),
          output_([[AVCaptureVideoDataOutput alloc] init]),
          queue_(dispatch_queue_create("com.swayamsingal.aether.capture", DISPATCH_QUEUE_SERIAL)) {}

    ~Impl() {
        (void)stop();
    }

    Result<FrameSourceInfo> start() {
        if (running_.load())
            return info_;

        const auto authorization =
            [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
        if (authorization == AVAuthorizationStatusNotDetermined)
            return fail(ErrorCode::unsupported,
                        "Camera permission has not been requested",
                        "Request AVMediaTypeVideo access before starting capture");
        if (authorization == AVAuthorizationStatusDenied)
            return fail(ErrorCode::unsupported, "Camera permission is denied");
        if (authorization == AVAuthorizationStatusRestricted)
            return fail(ErrorCode::unsupported, "Camera access is restricted");

        auto* device = [AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];
        if (!device)
            return fail(ErrorCode::notFound, "No AVFoundation video device is available");

        NSError* inputError = nil;
        auto* input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&inputError];
        if (!input) {
            const char* description =
                inputError.localizedDescription ? inputError.localizedDescription.UTF8String
                                                : "";
            return fail(ErrorCode::io, "Unable to create camera input",
                        description);
        }
        if (![session_ canAddInput:input])
            return fail(ErrorCode::unsupported, "Selected camera input cannot be added");
        [session_ addInput:input];

        output_.videoSettings = @{
            static_cast<NSString*>(kCVPixelBufferPixelFormatTypeKey):
                @(kCVPixelFormatType_32BGRA)
        };
        output_.alwaysDiscardsLateVideoFrames = YES;
        [output_ setSampleBufferDelegate:delegate_ queue:queue_];
        if (![session_ canAddOutput:output_]) {
            [session_ removeInput:input];
            return fail(ErrorCode::unsupported, "Camera video output cannot be added");
        }
        [session_ addOutput:output_];

        info_.sourceId =
            device.uniqueID ? device.uniqueID.UTF8String : "avfoundation-default";
        info_.sourceKind = CaptureSourceKind::camera;
        info_.displayName =
            device.localizedName ? device.localizedName.UTF8String : "Camera";
        [delegate_ setPacketCallback:packetCallback_ sourceId:info_.sourceId];
        running_.store(true);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            [this->session_ startRunning];
        });
        return info_;
    }

    Result<void> stop() {
        if (!running_.exchange(false))
            return {};
        [session_ stopRunning];
        [output_ setSampleBufferDelegate:nil queue:nullptr];
        for (AVCaptureInput* input in session_.inputs)
            [session_ removeInput:input];
        if ([session_.outputs containsObject:output_])
            [session_ removeOutput:output_];
        return {};
    }

    void setPacketCallback(PacketCallback callback) {
        std::lock_guard lock(callbackMutex_);
        packetCallback_ = std::move(callback);
        [delegate_ setPacketCallback:packetCallback_ sourceId:info_.sourceId];
    }

    void setErrorCallback(ErrorCallback callback) {
        std::lock_guard lock(callbackMutex_);
        errorCallback_ = std::move(callback);
    }

private:
    AetherCaptureDelegate* delegate_;
    AVCaptureSession* session_;
    AVCaptureVideoDataOutput* output_;
    dispatch_queue_t queue_;
    std::atomic<bool> running_{false};
    std::mutex callbackMutex_;
    PacketCallback packetCallback_;
    ErrorCallback errorCallback_;
    FrameSourceInfo info_;
};

AVFoundationFrameSource::AVFoundationFrameSource() : impl_(std::make_unique<Impl>()) {}
AVFoundationFrameSource::~AVFoundationFrameSource() = default;
Result<FrameSourceInfo> AVFoundationFrameSource::start() { return impl_->start(); }
Result<void> AVFoundationFrameSource::stop() { return impl_->stop(); }
void AVFoundationFrameSource::setPacketCallback(PacketCallback callback) {
    impl_->setPacketCallback(std::move(callback));
}
void AVFoundationFrameSource::setErrorCallback(ErrorCallback callback) {
    impl_->setErrorCallback(std::move(callback));
}

} // namespace aether::capture
