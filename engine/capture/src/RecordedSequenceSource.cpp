#include <aether/capture/RecordedSequenceSource.hpp>
#include <aether/package/Sha256.hpp>

#include <simdjson.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <limits>
#include <mutex>
#include <string_view>
#include <utility>
#include <vector>

namespace aether::capture {
namespace {

constexpr std::size_t maximumFrames = 1'000'000;
constexpr std::uint32_t maximumDimension = 16'384;
constexpr std::size_t maximumPlaneBytes = 512ULL * 1024ULL * 1024ULL;

struct PlaneRecord final {
    std::filesystem::path path;
    std::optional<std::string> sha256;
    PixelFormat format{PixelFormat::gray8};
    std::uint32_t width{};
    std::uint32_t height{};
    std::uint32_t rowStrideBytes{};
    std::size_t byteCount{};
    bool arkitConfidence{};
};

struct FrameRecord final {
    std::uint64_t frameId{};
    std::uint64_t presentationTimestampNs{};
    std::uint64_t timestampNs{};
    CameraCalibration calibration;
    std::vector<PlaneRecord> colorPlanes;
    PlaneRecord depth;
    std::optional<PlaneRecord> confidence;
    RigidPose pose;
    ImageOrientation orientation{ImageOrientation::up};
    bool mirrored{};
};

Result<std::string> stringField(simdjson::dom::element object, const char* field) {
    std::string_view value;
    if (object[field].get(value))
        return fail(ErrorCode::corruptData, "Capture manifest string field is invalid", field);
    return std::string(value);
}

Result<std::uint64_t> uintField(simdjson::dom::element object, const char* field) {
    std::uint64_t value{};
    if (object[field].get(value))
        return fail(ErrorCode::corruptData, "Capture manifest integer field is invalid", field);
    return value;
}

Result<double> numberField(simdjson::dom::element object, const char* field) {
    double value{};
    if (object[field].get(value) || !std::isfinite(value))
        return fail(ErrorCode::corruptData, "Capture manifest number field is invalid", field);
    return value;
}

Result<std::size_t> sizeField(simdjson::dom::element object, const char* field) {
    auto value = uintField(object, field);
    if (!value || *value > std::numeric_limits<std::size_t>::max())
        return fail(ErrorCode::corruptData, "Capture manifest size field is invalid", field);
    return static_cast<std::size_t>(*value);
}

Result<std::filesystem::path> relativePath(simdjson::dom::element object, const char* field) {
    auto text = stringField(object, field);
    if (!text)
        return std::unexpected(text.error());
    std::filesystem::path path(*text);
    if (path.empty() || path.is_absolute())
        return fail(ErrorCode::corruptData, "Capture path must be relative", field);
    for (const auto& component : path)
        if (component == "..")
            return fail(ErrorCode::corruptData, "Capture path traversal is forbidden", field);
    return path.lexically_normal();
}

template <std::size_t Size>
Result<std::array<double, Size>> numberArray(simdjson::dom::element object, const char* field) {
    simdjson::dom::array values;
    if (object[field].get_array().get(values) || values.size() != Size)
        return fail(ErrorCode::corruptData, "Capture manifest array has invalid length", field);
    std::array<double, Size> result{};
    std::size_t index = 0;
    for (auto value : values) {
        if (value.get(result[index]) || !std::isfinite(result[index]))
            return fail(ErrorCode::corruptData, "Capture manifest array contains invalid value",
                        field);
        ++index;
    }
    return result;
}

Result<std::vector<std::byte>> readExact(const std::filesystem::path& path,
                                         std::size_t expectedBytes,
                                         const std::optional<std::string>& expectedSha256 = {}) {
    if (expectedBytes == 0 || expectedBytes > maximumPlaneBytes)
        return fail(ErrorCode::resourceExhausted, "Recorded plane exceeds byte budget",
                    path.string());
    std::error_code error;
    const auto fileBytes = std::filesystem::file_size(path, error);
    if (error || fileBytes != expectedBytes)
        return fail(ErrorCode::corruptData, "Recorded plane byte count does not match manifest",
                    path.string());
    std::vector<std::byte> bytes(expectedBytes);
    std::ifstream stream(path, std::ios::binary);
    if (!stream.read(reinterpret_cast<char*>(bytes.data()),
                     static_cast<std::streamsize>(bytes.size())))
        return fail(ErrorCode::io, "Unable to read recorded plane", path.string());
    if (expectedSha256) {
        const auto digest = package::Sha256::hex(package::Sha256::hash(bytes));
        if (digest != *expectedSha256)
            return fail(ErrorCode::corruptData, "Recorded plane SHA-256 does not match manifest",
                        path.string());
    }
    return bytes;
}

Result<PlaneRecord> planeRecord(simdjson::dom::element object,
                                PixelFormat requiredFormat,
                                std::string_view requiredFormatName,
                                bool arkitConfidence = false) {
    auto path = relativePath(object, "path");
    auto sha256 = stringField(object, "sha256");
    auto width = uintField(object, "width");
    auto height = uintField(object, "height");
    auto rowStride = uintField(object, "rowStrideBytes");
    auto byteCount = sizeField(object, "byteCount");
    auto pixelFormat = stringField(object, "pixelFormat");
    if (!path || !sha256 || !width || !height || !rowStride || !byteCount || !pixelFormat)
        return fail(ErrorCode::corruptData, "Capture plane entry is incomplete");
    if (*pixelFormat != requiredFormatName)
        return fail(ErrorCode::unsupported, "Capture plane pixel format is unsupported",
                    *pixelFormat);
    if (sha256->size() != 64 ||
        !std::ranges::all_of(*sha256, [](char character) {
            return (character >= '0' && character <= '9') ||
                   (character >= 'a' && character <= 'f');
        }))
        return fail(ErrorCode::corruptData, "Capture plane SHA-256 is malformed",
                    path->string());
    std::uint64_t minimumStride = *width;
    if (requiredFormatName == "cbcr8x2")
        minimumStride *= 2;
    else if (requiredFormatName == "depth-f32-metres")
        minimumStride *= sizeof(float);
    if (*width == 0 || *height == 0 || *rowStride == 0 || *width > maximumDimension ||
        *height > maximumDimension || *rowStride > maximumPlaneBytes ||
        *rowStride < minimumStride ||
        *byteCount == 0 || *byteCount > maximumPlaneBytes ||
        *height > std::numeric_limits<std::size_t>::max() / *rowStride ||
        static_cast<std::size_t>(*height) * *rowStride != *byteCount)
        return fail(ErrorCode::resourceExhausted, "Capture plane dimensions exceed limits",
                    path->string());
    return PlaneRecord{*path,
                       *sha256,
                       requiredFormat,
                       static_cast<std::uint32_t>(*width),
                       static_cast<std::uint32_t>(*height),
                       static_cast<std::uint32_t>(*rowStride),
                       *byteCount,
                       arkitConfidence};
}

Result<CameraCalibration> calibrationV2(simdjson::dom::element object,
                                        std::string_view sourceId) {
    auto imageWidth = uintField(object, "imageWidth");
    auto imageHeight = uintField(object, "imageHeight");
    auto depthWidth = uintField(object, "depthWidth");
    auto depthHeight = uintField(object, "depthHeight");
    auto imageIntrinsics = numberArray<9>(object, "imageIntrinsics");
    auto depthIntrinsics = numberArray<9>(object, "depthIntrinsics");
    if (!imageWidth || !imageHeight || !depthWidth || !depthHeight ||
        !imageIntrinsics || !depthIntrinsics)
        return fail(ErrorCode::corruptData, "Capture frame calibration is incomplete");
    if (*imageWidth == 0 || *imageHeight == 0 || *depthWidth == 0 || *depthHeight == 0 ||
        *imageWidth > maximumDimension || *imageHeight > maximumDimension ||
        *depthWidth > maximumDimension || *depthHeight > maximumDimension)
        return fail(ErrorCode::corruptData, "Capture calibration dimensions are out of bounds");
    if ((*imageIntrinsics)[0] <= 0.0 || (*imageIntrinsics)[4] <= 0.0 ||
        (*imageIntrinsics)[6] < 0.0 || (*imageIntrinsics)[7] < 0.0)
        return fail(ErrorCode::corruptData, "Capture image intrinsics are invalid");

    CameraCalibration result;
    result.id = std::string(sourceId);
    result.width = static_cast<std::uint32_t>(*depthWidth);
    result.height = static_cast<std::uint32_t>(*depthHeight);
    // Swift stores simd matrices column-major.
    result.fx = (*depthIntrinsics)[0];
    result.fy = (*depthIntrinsics)[4];
    result.cx = (*depthIntrinsics)[6];
    result.cy = (*depthIntrinsics)[7];
    if (result.fx <= 0.0 || result.fy <= 0.0 || result.cx < 0.0 || result.cy < 0.0)
        return fail(ErrorCode::corruptData, "Capture depth intrinsics are invalid");
    return result;
}

Result<RigidPose> arkitPose(const std::array<double, 16>& matrix) {
    constexpr double tolerance = 2.0e-3;
    if (std::abs(matrix[3]) > tolerance || std::abs(matrix[7]) > tolerance ||
        std::abs(matrix[11]) > tolerance || std::abs(matrix[15] - 1.0) > tolerance)
        return fail(ErrorCode::corruptData, "ARKit camera transform is not affine");
    for (std::size_t column = 0; column < 3; ++column) {
        double lengthSquared = 0.0;
        for (std::size_t row = 0; row < 3; ++row)
            lengthSquared += matrix[column * 4 + row] * matrix[column * 4 + row];
        if (std::abs(lengthSquared - 1.0) > tolerance)
            return fail(ErrorCode::corruptData,
                        "ARKit camera transform rotation is not normalized");
        for (std::size_t other = column + 1; other < 3; ++other) {
            double dot = 0.0;
            for (std::size_t row = 0; row < 3; ++row)
                dot += matrix[column * 4 + row] * matrix[other * 4 + row];
            if (std::abs(dot) > tolerance)
                return fail(ErrorCode::corruptData,
                            "ARKit camera transform rotation is not orthogonal");
        }
    }
    const double determinant =
        matrix[0] * (matrix[5] * matrix[10] - matrix[9] * matrix[6]) -
        matrix[4] * (matrix[1] * matrix[10] - matrix[9] * matrix[2]) +
        matrix[8] * (matrix[1] * matrix[6] - matrix[5] * matrix[2]);
    if (std::abs(determinant - 1.0) > tolerance)
        return fail(ErrorCode::corruptData,
                    "ARKit camera transform rotation changes handedness");

    // ARKit camera coordinates use +Y up and -Z forward. Post-multiplying by
    // diag(1,-1,-1) gives the engine's image-aligned +Y down, +Z forward camera.
    const double r00 = matrix[0];
    const double r10 = matrix[1];
    const double r20 = matrix[2];
    const double r01 = -matrix[4];
    const double r11 = -matrix[5];
    const double r21 = -matrix[6];
    const double r02 = -matrix[8];
    const double r12 = -matrix[9];
    const double r22 = -matrix[10];

    std::array<double, 4> quaternion{};
    const double trace = r00 + r11 + r22;
    if (trace > 0.0) {
        const double scale = std::sqrt(trace + 1.0) * 2.0;
        quaternion = {0.25 * scale, (r21 - r12) / scale,
                      (r02 - r20) / scale, (r10 - r01) / scale};
    } else if (r00 > r11 && r00 > r22) {
        const double scale = std::sqrt(1.0 + r00 - r11 - r22) * 2.0;
        quaternion = {(r21 - r12) / scale, 0.25 * scale,
                      (r01 + r10) / scale, (r02 + r20) / scale};
    } else if (r11 > r22) {
        const double scale = std::sqrt(1.0 + r11 - r00 - r22) * 2.0;
        quaternion = {(r02 - r20) / scale, (r01 + r10) / scale,
                      0.25 * scale, (r12 + r21) / scale};
    } else {
        const double scale = std::sqrt(1.0 + r22 - r00 - r11) * 2.0;
        quaternion = {(r10 - r01) / scale, (r02 + r20) / scale,
                      (r12 + r21) / scale, 0.25 * scale};
    }
    const double norm = std::sqrt(quaternion[0] * quaternion[0] +
                                  quaternion[1] * quaternion[1] +
                                  quaternion[2] * quaternion[2] +
                                  quaternion[3] * quaternion[3]);
    if (norm > 0.0)
        for (double& value : quaternion)
            value /= norm;
    return RigidPose{quaternion, {matrix[12], matrix[13], matrix[14]}};
}

} // namespace

class RecordedSequenceSource::Impl final {
public:
    std::filesystem::path root;
    RecordedPlaybackConfig config;
    FrameSourceInfo info;
    std::vector<FrameRecord> frames;
    std::size_t cursor{};
    bool running{};
    PacketCallback packetCallback;
    ErrorCallback errorCallback;
    mutable std::mutex mutex;

    Result<CapturePacket> loadPacket(std::size_t index) const {
        const auto& record = frames[index];
        auto depth = readExact(root / record.depth.path, record.depth.byteCount,
                               record.depth.sha256);
        if (!depth)
            return std::unexpected(depth.error());

        CapturePacket packet;
        packet.frameId = record.frameId;
        packet.sourceId = info.sourceId;
        packet.sourceKind = info.sourceKind;
        packet.presentationTimestampNs = record.presentationTimestampNs;
        packet.hostTimestampNs = record.timestampNs;
        packet.orientation = record.orientation;
        packet.mirrored = record.mirrored;
        packet.calibration = record.calibration;
        packet.cameraToWorld = record.pose;
        for (const auto& plane : record.colorPlanes) {
            auto bytes = readExact(root / plane.path, plane.byteCount, plane.sha256);
            if (!bytes)
                return std::unexpected(bytes.error());
            packet.colorPlanes.push_back(ImagePlane{makeOwnedBuffer(std::move(*bytes)),
                                                    plane.format,
                                                    plane.width,
                                                    plane.height,
                                                    plane.rowStrideBytes});
        }
        packet.depthMetres = ImagePlane{
            makeOwnedBuffer(std::move(*depth)),
            record.depth.format,
            record.depth.width,
            record.depth.height,
            record.depth.rowStrideBytes,
        };
        if (record.confidence) {
            const auto& plane = *record.confidence;
            auto confidence = readExact(root / plane.path, plane.byteCount, plane.sha256);
            if (!confidence)
                return std::unexpected(confidence.error());
            if (plane.arkitConfidence) {
                for (std::uint32_t y = 0; y < plane.height; ++y) {
                    auto* row = confidence->data() +
                                static_cast<std::size_t>(y) * plane.rowStrideBytes;
                    for (std::uint32_t x = 0; x < plane.width; ++x) {
                        const auto raw = std::to_integer<std::uint8_t>(row[x]);
                        if (raw > 2)
                            return fail(ErrorCode::corruptData,
                                        "ARKit confidence contains an unknown level",
                                        plane.path.string());
                        row[x] = static_cast<std::byte>(
                            raw == 0 ? 0 : (raw == 1 ? 128 : 255));
                    }
                }
            }
            packet.depthConfidence = ImagePlane{
                makeOwnedBuffer(std::move(*confidence)),
                plane.format,
                plane.width,
                plane.height,
                plane.rowStrideBytes,
            };
        }
        return packet;
    }
};

Result<std::unique_ptr<RecordedSequenceSource>>
RecordedSequenceSource::open(const std::filesystem::path& directory,
                             RecordedPlaybackConfig config) {
    const auto manifestPath = directory / "manifest.json";
    simdjson::dom::parser parser;
    auto documentResult = parser.load(manifestPath.string());
    if (documentResult.error())
        return fail(ErrorCode::corruptData, "Unable to parse capture manifest",
                    manifestPath.string());
    simdjson::dom::element document = documentResult.value();

    auto schemaVersion = uintField(document, "schemaVersion");
    if (!schemaVersion || (*schemaVersion != 1 && *schemaVersion != 2))
        return fail(ErrorCode::unsupported, "Unsupported capture schema version",
                    schemaVersion ? std::to_string(*schemaVersion) : "missing");

    auto impl = std::make_unique<Impl>();
    impl->root = directory;
    impl->config = config;
    auto sourceId = stringField(document, "sourceId");
    if (!sourceId && *schemaVersion == 2)
        sourceId = stringField(document, "sourceID");
    if (!sourceId)
        return std::unexpected(sourceId.error());
    if (sourceId->empty() || sourceId->size() > 256)
        return fail(ErrorCode::corruptData, "Capture source identifier is invalid");
    const auto sourceKind = *schemaVersion == 2 ? CaptureSourceKind::lidar
                                                : CaptureSourceKind::recordedRgbd;
    impl->info = FrameSourceInfo{*sourceId, sourceKind,
                                 *schemaVersion == 2 ? "Recorded Apple LiDAR sequence"
                                                     : "Recorded RGB-D sequence",
                                 true, true, false};

    CameraCalibration legacyCalibration;
    if (*schemaVersion == 1) {
        simdjson::dom::element calibrationObject;
        if (document["calibration"].get(calibrationObject))
            return fail(ErrorCode::corruptData, "Capture calibration is missing");
        auto width = uintField(calibrationObject, "width");
        auto height = uintField(calibrationObject, "height");
        auto fx = numberField(calibrationObject, "fx");
        auto fy = numberField(calibrationObject, "fy");
        auto cx = numberField(calibrationObject, "cx");
        auto cy = numberField(calibrationObject, "cy");
        if (!width || !height || !fx || !fy || !cx || !cy)
            return fail(ErrorCode::corruptData, "Capture calibration is incomplete");
        if (*width == 0 || *height == 0 || *width > maximumDimension ||
            *height > maximumDimension || *fx <= 0.0 || *fy <= 0.0)
            return fail(ErrorCode::corruptData, "Capture calibration is out of bounds");
        legacyCalibration.id = *sourceId;
        legacyCalibration.width = static_cast<std::uint32_t>(*width);
        legacyCalibration.height = static_cast<std::uint32_t>(*height);
        legacyCalibration.fx = *fx;
        legacyCalibration.fy = *fy;
        legacyCalibration.cx = *cx;
        legacyCalibration.cy = *cy;
    } else {
        simdjson::dom::element coordinateSystem;
        if (document["coordinateSystem"].get(coordinateSystem))
            return fail(ErrorCode::corruptData,
                        "LiDAR capture coordinate system is missing");
        auto cameraConvention = stringField(coordinateSystem, "camera");
        auto poseConvention = stringField(coordinateSystem, "pose");
        auto depthUnit = stringField(coordinateSystem, "depthUnit");
        auto intrinsicsConvention = stringField(coordinateSystem, "intrinsics");
        if (!cameraConvention || !poseConvention || !depthUnit ||
            !intrinsicsConvention ||
            *cameraConvention != "ARKit right-handed: +X right, +Y up, -Z forward" ||
            *poseConvention != "column-major camera-to-world 4x4 matrix" ||
            *depthUnit != "metres" ||
            *intrinsicsConvention != "3x3 column-major pixels")
            return fail(ErrorCode::unsupported,
                        "LiDAR capture coordinate convention is unsupported");
    }

    simdjson::dom::array frames;
    if (document["frames"].get_array().get(frames) || frames.size() == 0 ||
        frames.size() > maximumFrames)
        return fail(ErrorCode::corruptData, "Capture frame list is empty or exceeds its budget");
    std::uint64_t previousFrameId = 0;
    std::uint64_t previousTimestamp = 0;
    for (auto frameObject : frames) {
        FrameRecord record;
        auto frameId = uintField(frameObject, *schemaVersion == 2 ? "frameID" : "frameId");
        auto timestamp = uintField(frameObject, *schemaVersion == 2
                                                    ? "hostTimestampNanoseconds"
                                                    : "timestampNs");
        if (!frameId || !timestamp)
            return fail(ErrorCode::corruptData, "Capture frame identity is incomplete");
        if (*frameId <= previousFrameId || *timestamp < previousTimestamp)
            return fail(ErrorCode::corruptData,
                        "Capture frame IDs and timestamps must be ordered");
        record.frameId = *frameId;
        record.presentationTimestampNs = *timestamp;
        record.timestampNs = *timestamp;

        if (*schemaVersion == 1) {
            auto colorPath = relativePath(frameObject, "color");
            auto depthPath = relativePath(frameObject, "depth");
            auto orientation = numberArray<4>(frameObject, "orientation");
            auto translation = numberArray<3>(frameObject, "translation");
            if (!colorPath || !depthPath || !orientation || !translation)
                return fail(ErrorCode::corruptData, "Capture frame entry is incomplete");
            const auto pixelCount = static_cast<std::size_t>(legacyCalibration.width) *
                                    legacyCalibration.height;
            record.calibration = legacyCalibration;
            record.colorPlanes.push_back(
                PlaneRecord{*colorPath, {}, PixelFormat::rgb8,
                            legacyCalibration.width, legacyCalibration.height,
                            legacyCalibration.width * 3, pixelCount * 3});
            record.depth = PlaneRecord{
                *depthPath, {}, PixelFormat::depthFloat32Metres,
                legacyCalibration.width, legacyCalibration.height,
                legacyCalibration.width * static_cast<std::uint32_t>(sizeof(float)),
                pixelCount * sizeof(float)};
            record.pose.orientation = *orientation;
            record.pose.translation = *translation;
            auto confidenceField = frameObject["confidence"];
            if (confidenceField.error() != simdjson::NO_SUCH_FIELD) {
                std::string_view confidenceText;
                if (confidenceField.get(confidenceText))
                    return fail(ErrorCode::corruptData,
                                "Confidence path must be a string when present");
                std::filesystem::path confidence(confidenceText);
                if (confidence.empty() || confidence.is_absolute())
                    return fail(ErrorCode::corruptData, "Confidence path must be relative");
                for (const auto& component : confidence)
                    if (component == "..")
                        return fail(ErrorCode::corruptData,
                                    "Confidence path traversal is forbidden");
                record.confidence = PlaneRecord{
                    confidence.lexically_normal(), {}, PixelFormat::confidenceUInt8,
                    legacyCalibration.width, legacyCalibration.height,
                    legacyCalibration.width, pixelCount};
            }
        } else {
            auto trackingState = stringField(frameObject, "cameraTrackingState");
            auto imageOrientation = stringField(frameObject, "nativeImageOrientation");
            bool mirrored{};
            if (!trackingState || *trackingState != "normal" ||
                !imageOrientation || *imageOrientation != "landscapeRight" ||
                frameObject["mirrored"].get(mirrored) || mirrored)
                return fail(ErrorCode::corruptData,
                            "LiDAR capture tracking or native image orientation is invalid");
            record.orientation = ImageOrientation::right;
            record.mirrored = false;
            auto arTimestamp = numberField(frameObject, "arTimestampSeconds");
            if (!arTimestamp || *arTimestamp < 0.0 ||
                *arTimestamp > static_cast<double>(
                    std::numeric_limits<std::uint64_t>::max()) / 1.0e9)
                return fail(ErrorCode::corruptData,
                            "LiDAR capture AR timestamp is invalid");
            record.presentationTimestampNs =
                static_cast<std::uint64_t>(std::llround(*arTimestamp * 1.0e9));
            simdjson::dom::element calibrationObject;
            simdjson::dom::element lumaObject;
            simdjson::dom::element chromaObject;
            simdjson::dom::element depthObject;
            if (frameObject["calibration"].get(calibrationObject) ||
                frameObject["luma"].get(lumaObject) ||
                frameObject["chroma"].get(chromaObject) ||
                frameObject["depth"].get(depthObject))
                return fail(ErrorCode::corruptData, "LiDAR capture frame is incomplete");
            auto calibration = calibrationV2(calibrationObject, *sourceId);
            auto luma = planeRecord(lumaObject, PixelFormat::yuv420BiPlanarVideoRange, "y8");
            auto chroma = planeRecord(chromaObject, PixelFormat::yuv420BiPlanarVideoRange,
                                      "cbcr8x2");
            auto depth = planeRecord(depthObject, PixelFormat::depthFloat32Metres,
                                     "depth-f32-metres");
            auto matrix = numberArray<16>(frameObject, "cameraToWorld");
            if (!calibration || !luma || !chroma || !depth || !matrix)
                return fail(ErrorCode::corruptData,
                            "LiDAR capture frame calibration or planes are invalid");
            if (depth->width != calibration->width ||
                depth->height != calibration->height ||
                luma->width != uintField(calibrationObject, "imageWidth").value_or(0) ||
                luma->height != uintField(calibrationObject, "imageHeight").value_or(0) ||
                chroma->width * 2 != luma->width ||
                chroma->height * 2 != luma->height)
                return fail(ErrorCode::corruptData,
                            "LiDAR capture plane dimensions disagree with calibration");
            record.calibration = *calibration;
            record.colorPlanes = {*luma, *chroma};
            record.depth = *depth;
            auto convertedPose = arkitPose(*matrix);
            if (!convertedPose)
                return std::unexpected(convertedPose.error());
            record.pose = *convertedPose;

            auto confidenceField = frameObject["confidence"];
            if (confidenceField.error() != simdjson::NO_SUCH_FIELD &&
                !confidenceField.is_null()) {
                simdjson::dom::element confidenceObject;
                if (confidenceField.get(confidenceObject))
                    return fail(ErrorCode::corruptData,
                                "LiDAR confidence plane is invalid");
                auto confidence = planeRecord(confidenceObject,
                                              PixelFormat::confidenceUInt8,
                                              "arkit-confidence-u8", true);
                if (!confidence ||
                    confidence->width != calibration->width ||
                    confidence->height != calibration->height)
                    return fail(ErrorCode::corruptData,
                                "LiDAR confidence dimensions are invalid");
                record.confidence = *confidence;
            }

            simdjson::dom::element exposureObject;
            if (!frameObject["exposure"].get(exposureObject)) {
                auto duration = numberField(exposureObject, "durationSeconds");
                auto offset = numberField(exposureObject, "exposureOffsetEV");
                if (!duration || !offset || *duration < 0.0)
                    return fail(ErrorCode::corruptData,
                                "LiDAR capture exposure is invalid");
            }
        }
        impl->frames.push_back(std::move(record));
        previousFrameId = *frameId;
        previousTimestamp = *timestamp;
    }
    return std::unique_ptr<RecordedSequenceSource>(
        new RecordedSequenceSource(std::move(impl)));
}

RecordedSequenceSource::RecordedSequenceSource(std::unique_ptr<Impl> impl)
    : impl_(std::move(impl)) {}
RecordedSequenceSource::~RecordedSequenceSource() = default;

Result<FrameSourceInfo> RecordedSequenceSource::start() {
    std::lock_guard lock(impl_->mutex);
    impl_->running = true;
    return impl_->info;
}

Result<void> RecordedSequenceSource::stop() {
    std::lock_guard lock(impl_->mutex);
    impl_->running = false;
    return {};
}

void RecordedSequenceSource::setPacketCallback(PacketCallback callback) {
    std::lock_guard lock(impl_->mutex);
    impl_->packetCallback = std::move(callback);
}

void RecordedSequenceSource::setErrorCallback(ErrorCallback callback) {
    std::lock_guard lock(impl_->mutex);
    impl_->errorCallback = std::move(callback);
}

Result<bool> RecordedSequenceSource::step() {
    std::size_t index{};
    PacketCallback callback;
    ErrorCallback errorCallback;
    {
        std::lock_guard lock(impl_->mutex);
        if (!impl_->running)
            return fail(ErrorCode::invalidArgument, "Recorded source is not running");
        if (impl_->cursor >= impl_->frames.size())
            return false;
        index = impl_->cursor++;
        callback = impl_->packetCallback;
        errorCallback = impl_->errorCallback;
    }
    if (impl_->config.injectedFailureFrame &&
        index == *impl_->config.injectedFailureFrame) {
        auto error = Error{ErrorCode::io, "Injected recorded-source failure",
                           std::to_string(index)};
        if (errorCallback)
            errorCallback(error);
        return std::unexpected(std::move(error));
    }
    auto packet = impl_->loadPacket(index);
    if (!packet) {
        if (errorCallback)
            errorCallback(packet.error());
        return std::unexpected(packet.error());
    }
    if (callback)
        callback(std::move(*packet));
    return true;
}

void RecordedSequenceSource::rewind() noexcept {
    std::lock_guard lock(impl_->mutex);
    impl_->cursor = 0;
}

std::size_t RecordedSequenceSource::frameCount() const noexcept {
    return impl_->frames.size();
}

std::size_t RecordedSequenceSource::position() const noexcept {
    std::lock_guard lock(impl_->mutex);
    return impl_->cursor;
}

} // namespace aether::capture
