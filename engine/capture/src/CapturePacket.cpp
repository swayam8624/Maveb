#include <aether/capture/CapturePacket.hpp>

#include <limits>

namespace aether::capture {

namespace {
std::size_t bytesPerPixel(PixelFormat format) noexcept {
    switch (format) {
    case PixelFormat::gray8:
    case PixelFormat::confidenceUInt8:
        return 1;
    case PixelFormat::rgb8:
        return 3;
    case PixelFormat::bgra8:
    case PixelFormat::depthFloat32Metres:
        return 4;
    case PixelFormat::yuv420BiPlanarVideoRange:
        return 1;
    }
    return 0;
}
} // namespace

bool ImagePlane::valid() const noexcept {
    if (!buffer.valid() || width == 0 || height == 0 || rowStrideBytes == 0)
        return false;
    const auto pixelBytes = bytesPerPixel(format);
    if (pixelBytes == 0 || width > std::numeric_limits<std::size_t>::max() / pixelBytes)
        return false;
    const auto minimumStride = static_cast<std::size_t>(width) * pixelBytes;
    if (rowStrideBytes < minimumStride)
        return false;
    return height <= std::numeric_limits<std::size_t>::max() / rowStrideBytes &&
           buffer.sizeBytes >= static_cast<std::size_t>(height) * rowStrideBytes;
}

bool CapturePacket::hasMetricDepth() const noexcept {
    return depthMetres && depthMetres->format == PixelFormat::depthFloat32Metres &&
           depthMetres->valid();
}

BufferView makeOwnedBuffer(std::vector<std::byte> bytes) {
    auto storage = std::make_shared<const std::vector<std::byte>>(std::move(bytes));
    return BufferView{storage, storage->data(), storage->size()};
}

} // namespace aether::capture
