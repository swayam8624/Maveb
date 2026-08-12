#include <aether/capture/CaptureValidator.hpp>
#include <aether/capture/KeyframeSelector.hpp>
#include <aether/capture/RecordedSequenceSource.hpp>

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
bool writePng(const std::filesystem::path& path, std::uint8_t base, bool checkerboard) {
    constexpr std::size_t width = 64;
    constexpr std::size_t height = 64;
    std::vector<std::uint8_t> pixels(width * height);
    for (std::size_t y = 0; y < height; ++y)
        for (std::size_t x = 0; x < width; ++x)
            pixels[y * width + x] = checkerboard && ((x / 4 + y / 4) % 2) ? 255 : base;
    auto space = CGColorSpaceCreateDeviceGray();
    auto provider = CGDataProviderCreateWithData(nullptr, pixels.data(), pixels.size(), nullptr);
    auto image = CGImageCreate(width, height, 8, 8, width, space, kCGImageAlphaNone, provider,
                               nullptr, false, kCGRenderingIntentDefault);
    auto url = CFURLCreateFromFileSystemRepresentation(
        nullptr, reinterpret_cast<const UInt8*>(path.c_str()),
        static_cast<CFIndex>(path.string().size()), false);
    auto destination = CGImageDestinationCreateWithURL(url, CFSTR("public.png"), 1, nullptr);
    if (destination)
        CGImageDestinationAddImage(destination, image, nullptr);
    const bool written = destination && CGImageDestinationFinalize(destination);
    if (destination)
        CFRelease(destination);
    CFRelease(url);
    CGImageRelease(image);
    CGDataProviderRelease(provider);
    CGColorSpaceRelease(space);
    return written;
}

bool require(bool condition, const char* message) {
    if (!condition)
        std::cerr << "FAIL: " << message << '\n';
    return condition;
}
} // namespace

int runTests() {
    const auto root = std::filesystem::temp_directory_path() / "aether-capture-tests";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    if (!writePng(root / "01.png", 32, true) || !writePng(root / "02.png", 64, true) ||
        !writePng(root / "03.png", 120, false))
        return 1;

    const auto report = aether::capture::validateCapture(root);
    bool okay = true;
    okay &= require(report.valid(), "three real PNGs should validate");
    okay &= require(report.images.size() == 3, "all images should be decoded");
    okay &= require(report.sourceBytes > 0, "source bytes should be measured");
    okay &= require(report.medianSharpness > 0, "checkerboard sharpness should be non-zero");
    okay &= require(report.exposureSpreadStops > 0, "luminance spread should be measured");
    okay &= require(std::ranges::any_of(report.images.front().appearanceFingerprint,
                                        [](std::uint8_t value) { return value != 0; }),
                    "capture validation emits a bounded appearance fingerprint");

    aether::capture::CaptureReport keyframeCapture;
    keyframeCapture.medianSharpness = 100.0;
    constexpr std::array<std::size_t, 5> variants{0, 0, 1, 1, 2};
    for (std::size_t index = 0; index < variants.size(); ++index) {
        aether::capture::ImageMeasurement image;
        image.path = root / ("frame-" + std::to_string(index) + ".png");
        image.meanLuminance = 0.5;
        image.luminanceDeviation = 0.2;
        image.sharpness = index == 3 ? 1.0 : 100.0;
        for (std::size_t y = 0; y < aether::capture::ImageMeasurement::fingerprintHeight; ++y)
            for (std::size_t x = 0; x < aether::capture::ImageMeasurement::fingerprintWidth; ++x) {
                const std::size_t fingerprintIndex =
                    y * aether::capture::ImageMeasurement::fingerprintWidth + x;
                if (variants[index] == 0)
                    image.appearanceFingerprint[fingerprintIndex] =
                        static_cast<std::uint8_t>(x * 16);
                else if (variants[index] == 1)
                    image.appearanceFingerprint[fingerprintIndex] =
                        static_cast<std::uint8_t>(((x + 4) % 16) * 16);
                else
                    image.appearanceFingerprint[fingerprintIndex] =
                        static_cast<std::uint8_t>(y * 16);
            }
        keyframeCapture.images.push_back(std::move(image));
    }
    aether::capture::KeyframeSelectionOptions keyframeOptions;
    keyframeOptions.minimumFrameGap = 1;
    keyframeOptions.maximumAppearanceDistance = 1.0;
    const auto keyframes = aether::capture::selectKeyframes(keyframeCapture, keyframeOptions);
    okay &= require(keyframes.valid() && keyframes.selectedImages.size() == 3,
                    "keyframe selection retains useful appearance changes");
    okay &= require(keyframes.decisions[1].reason == "near-duplicate" &&
                        keyframes.decisions[3].reason == "relative-blur",
                    "keyframe selection reports duplicate and blur rejection reasons");

    std::ofstream(root / "broken.jpg") << "not an image";
    const auto broken = aether::capture::validateCapture(root);
    okay &=
        require(!broken.valid(), "a supported-extension decode failure must invalidate capture");
    okay &= require(
        std::ranges::any_of(broken.issues,
                            [](const auto& issue) { return issue.code == "image-decode-failed"; }),
        "decode failure should have a structured issue code");

    const auto sequence = root / "sequence";
    std::filesystem::create_directories(sequence);
    {
        constexpr std::array<std::uint8_t, 12> color{255, 0, 0,   0,   255, 0,
                                                     0,   0, 255, 255, 255, 255};
        std::ofstream colorFile(sequence / "color.raw", std::ios::binary);
        colorFile.write(reinterpret_cast<const char*>(color.data()),
                        static_cast<std::streamsize>(color.size()));
        constexpr std::array<float, 4> depth{1.0F, 1.0F, 1.0F, 1.0F};
        std::ofstream depthFile(sequence / "depth.f32", std::ios::binary);
        depthFile.write(reinterpret_cast<const char*>(depth.data()),
                        static_cast<std::streamsize>(sizeof(depth)));
        std::ofstream manifest(sequence / "manifest.json");
        manifest << R"({
  "schemaVersion": 1,
  "sourceId": "recorded-fixture",
  "calibration": {"width": 2, "height": 2, "fx": 2.0, "fy": 2.0, "cx": 0.5, "cy": 0.5},
  "frames": [{
    "frameId": 1,
    "timestampNs": 1000,
    "color": "color.raw",
    "depth": "depth.f32",
    "orientation": [1.0, 0.0, 0.0, 0.0],
    "translation": [0.0, 0.0, 0.0]
  }]
})";
    }
    auto recorded = aether::capture::RecordedSequenceSource::open(sequence);
    okay &= require(recorded.has_value() && (*recorded)->frameCount() == 1,
                    "Versioned recorded RGB-D sequence opens deterministically");
    if (recorded) {
        std::size_t delivered = 0;
        (*recorded)->setPacketCallback([&](const aether::capture::CapturePacket& packet) {
            ++delivered;
            okay &= require(packet.frameId == 1 && packet.hasMetricDepth() &&
                                packet.cameraToWorld.has_value(),
                            "Recorded source delivers synchronized pose and metric depth");
        });
        okay &= require((*recorded)->start().has_value(), "Recorded source starts explicitly");
        auto stepped = (*recorded)->step();
        okay &= require(stepped.has_value() && *stepped && delivered == 1,
                        "Recorded source emits exactly one packet per step");
        stepped = (*recorded)->step();
        okay &= require(stepped.has_value() && !*stepped,
                        "Recorded source reports deterministic end of sequence");
        okay &= require((*recorded)->stop().has_value(), "Recorded source stops cleanly");
    }

    auto injected = aether::capture::RecordedSequenceSource::open(
        sequence, aether::capture::RecordedPlaybackConfig{0});
    if (injected) {
        bool reported = false;
        (*injected)->setErrorCallback([&](const aether::Error&) { reported = true; });
        okay &= require((*injected)->start().has_value(),
                        "Fault-injected recorded source starts before deterministic failure");
        okay &= require(!(*injected)->step().has_value() && reported,
                        "Recorded source fault injection propagates a structured failure");
    }

    const auto lidarSequence = root / "lidar-sequence";
    std::filesystem::create_directories(lidarSequence / "color");
    std::filesystem::create_directories(lidarSequence / "depth");
    std::filesystem::create_directories(lidarSequence / "confidence");
    {
        constexpr std::array<std::uint8_t, 4> luma{16, 64, 128, 235};
        constexpr std::array<std::uint8_t, 2> chroma{128, 128};
        constexpr std::array<float, 4> depth{1.0F, 1.0F, 1.0F, 1.0F};
        constexpr std::array<std::uint8_t, 4> confidence{0, 1, 2, 2};
        std::ofstream(lidarSequence / "color/000001.y8", std::ios::binary)
            .write(reinterpret_cast<const char*>(luma.data()), luma.size());
        std::ofstream(lidarSequence / "color/000001.cbcr8x2", std::ios::binary)
            .write(reinterpret_cast<const char*>(chroma.data()), chroma.size());
        std::ofstream(lidarSequence / "depth/000001.f32", std::ios::binary)
            .write(reinterpret_cast<const char*>(depth.data()), sizeof(depth));
        std::ofstream(lidarSequence / "confidence/000001.u8", std::ios::binary)
            .write(reinterpret_cast<const char*>(confidence.data()), confidence.size());
        std::ofstream manifest(lidarSequence / "manifest.json");
        manifest << R"({
  "schemaVersion": 2,
  "sourceID": "ipad-lidar-fixture",
  "coordinateSystem": {
    "camera": "ARKit right-handed: +X right, +Y up, -Z forward",
    "pose": "column-major camera-to-world 4x4 matrix",
    "depthUnit": "metres",
    "intrinsics": "3x3 column-major pixels"
  },
  "frames": [{
    "frameID": 1,
    "arTimestampSeconds": 0.0000015,
    "hostTimestampNanoseconds": 2000,
    "nativeImageOrientation": "landscapeRight",
    "mirrored": false,
    "cameraTrackingState": "normal",
    "cameraToWorld": [1,0,0,0, 0,1,0,0, 0,0,1,0, 1,2,3,1],
    "calibration": {
      "imageWidth": 2, "imageHeight": 2, "depthWidth": 2, "depthHeight": 2,
      "imageIntrinsics": [2,0,0, 0,2,0, 0.5,0.5,1],
      "depthIntrinsics": [2,0,0, 0,2,0, 0.5,0.5,1]
    },
    "luma": {
      "path": "color/000001.y8",
      "sha256": "c9630c3201527b5af73017cb113368f7cbc7d0d5310b78c3dfb4db3462afee30",
      "width": 2, "height": 2, "rowStrideBytes": 2,
      "pixelFormat": "y8", "byteCount": 4
    },
    "chroma": {
      "path": "color/000001.cbcr8x2",
      "sha256": "af472cf2977dbfccc45851e12525627fc9ecc03f274f108a865b18a672f38ba6",
      "width": 1, "height": 1, "rowStrideBytes": 2,
      "pixelFormat": "cbcr8x2", "byteCount": 2
    },
    "depth": {
      "path": "depth/000001.f32",
      "sha256": "f6bb1294da2f78cd935b01c7656280df5eaa0439e9d97bc03775825a41a508e4",
      "width": 2, "height": 2, "rowStrideBytes": 8,
      "pixelFormat": "depth-f32-metres", "byteCount": 16
    },
    "confidence": {
      "path": "confidence/000001.u8",
      "sha256": "69aa81d76a2198545225f9bec4a345cfac7141bf4ca24de6a71ea7854a943305",
      "width": 2, "height": 2, "rowStrideBytes": 2,
      "pixelFormat": "arkit-confidence-u8", "byteCount": 4
    },
    "exposure": {"durationSeconds": 0.008, "exposureOffsetEV": 0}
  }]
})";
    }
    auto lidar = aether::capture::RecordedSequenceSource::open(lidarSequence);
    okay &= require(lidar.has_value() && (*lidar)->frameCount() == 1,
                    "MavebCapture schema v2 opens as a recorded LiDAR source");
    if (lidar) {
        (*lidar)->setPacketCallback([&](aether::capture::CapturePacket packet) {
            okay &= require(packet.sourceKind == aether::capture::CaptureSourceKind::lidar &&
                                packet.colorPlanes.size() == 2 && packet.hasMetricDepth(),
                            "LiDAR source preserves YUV color and metric depth planes");
            okay &= require(packet.calibration.width == 2 && packet.calibration.fx == 2.0 &&
                                packet.cameraToWorld.has_value() &&
                                packet.cameraToWorld->translation ==
                                    std::array<double, 3>{1.0, 2.0, 3.0},
                            "LiDAR source preserves calibrated depth and world translation");
            okay &= require(packet.cameraToWorld->orientation[1] == 1.0,
                            "ARKit camera axes convert to the engine camera convention");
            okay &= require(packet.depthConfidence.has_value(),
                            "LiDAR source preserves its confidence plane");
            const auto* confidenceBytes =
                packet.depthConfidence ? packet.depthConfidence->buffer.data : nullptr;
            okay &= require(confidenceBytes != nullptr &&
                                std::to_integer<std::uint8_t>(confidenceBytes[0]) == 0 &&
                                std::to_integer<std::uint8_t>(confidenceBytes[1]) == 128 &&
                                std::to_integer<std::uint8_t>(confidenceBytes[2]) == 255,
                            "ARKit confidence levels normalize to fusion weights");
        });
        okay &= require((*lidar)->start().has_value() && (*lidar)->step().value_or(false) &&
                            (*lidar)->stop().has_value(),
                        "LiDAR capture replays after checksum verification");
    }
    {
        constexpr std::array<std::uint8_t, 4> damagedLuma{17, 64, 128, 235};
        std::ofstream(lidarSequence / "color/000001.y8", std::ios::binary | std::ios::trunc)
            .write(reinterpret_cast<const char*>(damagedLuma.data()), damagedLuma.size());
        auto damaged = aether::capture::RecordedSequenceSource::open(lidarSequence);
        okay &= require(damaged.has_value(), "LiDAR manifest remains structurally readable");
        if (damaged) {
            okay &= require((*damaged)->start().has_value(),
                            "Damaged LiDAR source starts before checksum validation");
            okay &= require(!(*damaged)->step().has_value(),
                            "LiDAR replay rejects a plane whose checksum changed");
        }
    }

    {
        std::ofstream manifest(sequence / "manifest.json", std::ios::trunc);
        manifest << R"({
  "schemaVersion": 1,
  "sourceId": "hostile",
  "calibration": {"width": 2, "height": 2, "fx": 2.0, "fy": 2.0, "cx": 0.5, "cy": 0.5},
  "frames": [{
    "frameId": 1,
    "timestampNs": 1,
    "color": "../outside.raw",
    "depth": "depth.f32",
    "orientation": [1.0, 0.0, 0.0, 0.0],
    "translation": [0.0, 0.0, 0.0]
  }]
})";
    }
    okay &= require(!aether::capture::RecordedSequenceSource::open(sequence).has_value(),
                    "Recorded capture rejects manifest path traversal");
    std::filesystem::remove_all(root);
    return okay ? 0 : 1;
}

int main() noexcept {
    try {
        return runTests();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unhandled capture-test exception: " << error.what() << '\n';
    } catch (...) {
        std::cerr << "FAIL: unhandled capture-test exception\n";
    }
    return 1;
}
