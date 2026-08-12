#include <aether/capture/CaptureValidator.hpp>

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/CGImageProperties.h>
#include <ImageIO/ImageIO.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <numeric>
#include <set>

namespace aether::capture {
namespace {
template <typename T> class CfOwner {
  public:
    explicit CfOwner(T value = nullptr) : value_(value) {}
    ~CfOwner() {
        if (value_)
            CFRelease(value_);
    }
    CfOwner(const CfOwner&) = delete;
    CfOwner& operator=(const CfOwner&) = delete;
    T get() const {
        return value_;
    }

  private:
    T value_;
};

std::optional<double> number(CFDictionaryRef dictionary, CFStringRef key) {
    if (!dictionary)
        return std::nullopt;
    const auto value = static_cast<CFNumberRef>(CFDictionaryGetValue(dictionary, key));
    if (!value || CFGetTypeID(value) != CFNumberGetTypeID())
        return std::nullopt;
    double result{};
    if (!CFNumberGetValue(value, kCFNumberDoubleType, &result))
        return std::nullopt;
    return result;
}

std::string string(CFDictionaryRef dictionary, CFStringRef key) {
    if (!dictionary)
        return {};
    const auto value = static_cast<CFStringRef>(CFDictionaryGetValue(dictionary, key));
    if (!value || CFGetTypeID(value) != CFStringGetTypeID())
        return {};
    const auto length = CFStringGetLength(value);
    const auto bytes = CFStringGetMaximumSizeForEncoding(length, kCFStringEncodingUTF8) + 1;
    std::string result(static_cast<std::size_t>(bytes), '\0');
    if (!CFStringGetCString(value, result.data(), bytes, kCFStringEncodingUTF8))
        return {};
    result.resize(std::char_traits<char>::length(result.c_str()));
    return result;
}

bool supported(const std::filesystem::path& path) {
    auto extension = path.extension().string();
    std::transform(extension.begin(), extension.end(), extension.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    static const std::set<std::string> extensions{
        ".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".arw", ".cr2", ".nef"};
    return extensions.contains(extension);
}

std::optional<ImageMeasurement> measure(const std::filesystem::path& path,
                                        std::size_t maximumDimension) {
    const auto pathString = path.string();
    CfOwner<CFURLRef> url(CFURLCreateFromFileSystemRepresentation(
        nullptr, reinterpret_cast<const UInt8*>(pathString.c_str()),
        static_cast<CFIndex>(pathString.size()), false));
    CfOwner<CGImageSourceRef> source(url.get() ? CGImageSourceCreateWithURL(url.get(), nullptr)
                                               : nullptr);
    if (!source.get() || CGImageSourceGetCount(source.get()) == 0)
        return std::nullopt;

    CfOwner<CFDictionaryRef> properties(
        CGImageSourceCopyPropertiesAtIndex(source.get(), 0, nullptr));
    auto widthValue = number(properties.get(), kCGImagePropertyPixelWidth);
    auto heightValue = number(properties.get(), kCGImagePropertyPixelHeight);
    constexpr double maximumImageDimension = 200000.0;
    if (!widthValue || !heightValue || *widthValue <= 0 || *heightValue <= 0 ||
        *widthValue > maximumImageDimension || *heightValue > maximumImageDimension)
        return std::nullopt;

    const auto maximumDimensionValue = static_cast<long>(maximumDimension);
    const auto thumbnailSize = static_cast<CFNumberRef>(
        CFNumberCreate(nullptr, kCFNumberLongType, &maximumDimensionValue));
    CfOwner<CFNumberRef> thumbnailSizeOwner(thumbnailSize);
    const void* keys[]{kCGImageSourceCreateThumbnailFromImageAlways,
                       kCGImageSourceCreateThumbnailWithTransform,
                       kCGImageSourceThumbnailMaxPixelSize};
    const void* values[]{kCFBooleanTrue, kCFBooleanTrue, thumbnailSize};
    CfOwner<CFDictionaryRef> thumbnailOptions(CFDictionaryCreate(nullptr, keys, values, 3,
                                                                 &kCFTypeDictionaryKeyCallBacks,
                                                                 &kCFTypeDictionaryValueCallBacks));
    CfOwner<CGImageRef> image(
        CGImageSourceCreateThumbnailAtIndex(source.get(), 0, thumbnailOptions.get()));
    if (!image.get())
        return std::nullopt;

    const auto width = CGImageGetWidth(image.get());
    const auto height = CGImageGetHeight(image.get());
    std::vector<std::uint8_t> pixels(width * height);
    CfOwner<CGColorSpaceRef> colourSpace(CGColorSpaceCreateDeviceGray());
    CfOwner<CGContextRef> context(CGBitmapContextCreate(pixels.data(), width, height, 8, width,
                                                        colourSpace.get(), kCGImageAlphaNone));
    if (!context.get())
        return std::nullopt;
    CGContextDrawImage(context.get(),
                       CGRectMake(0, 0, static_cast<CGFloat>(width), static_cast<CGFloat>(height)),
                       image.get());

    const double mean = std::accumulate(pixels.begin(), pixels.end(), 0.0) /
                        (255.0 * static_cast<double>(pixels.size()));
    double variance = 0.0;
    for (auto pixel : pixels) {
        const auto delta = static_cast<double>(pixel) / 255.0 - mean;
        variance += delta * delta;
    }
    variance /= static_cast<double>(pixels.size());

    double laplacianEnergy = 0.0;
    std::size_t laplacianCount = 0;
    for (std::size_t y = 1; y + 1 < height; ++y) {
        for (std::size_t x = 1; x + 1 < width; ++x) {
            const auto center = static_cast<double>(pixels[y * width + x]);
            const auto laplacian = 4.0 * center - pixels[(y - 1) * width + x] -
                                   pixels[(y + 1) * width + x] - pixels[y * width + x - 1] -
                                   pixels[y * width + x + 1];
            laplacianEnergy += laplacian * laplacian;
            ++laplacianCount;
        }
    }

    ImageMeasurement result;
    result.path = path;
    std::error_code sizeError;
    result.fileBytes = std::filesystem::file_size(path, sizeError);
    if (sizeError)
        return std::nullopt;
    result.width = static_cast<std::size_t>(*widthValue);
    result.height = static_cast<std::size_t>(*heightValue);
    result.meanLuminance = mean;
    result.luminanceDeviation = std::sqrt(variance);
    result.sharpness = laplacianCount ? laplacianEnergy / static_cast<double>(laplacianCount) : 0.0;
    const auto exif = properties.get() ? static_cast<CFDictionaryRef>(CFDictionaryGetValue(
                                             properties.get(), kCGImagePropertyExifDictionary))
                                       : nullptr;
    result.exposureSeconds = number(exif, kCGImagePropertyExifExposureTime);
    result.fNumber = number(exif, kCGImagePropertyExifFNumber);
    result.focalLengthMillimetres = number(exif, kCGImagePropertyExifFocalLength);
    if (exif) {
        const auto isoArray = static_cast<CFArrayRef>(
            CFDictionaryGetValue(exif, kCGImagePropertyExifISOSpeedRatings));
        if (isoArray && CFGetTypeID(isoArray) == CFArrayGetTypeID() &&
            CFArrayGetCount(isoArray) > 0) {
            const auto isoNumber = static_cast<CFNumberRef>(CFArrayGetValueAtIndex(isoArray, 0));
            double iso{};
            if (isoNumber && CFNumberGetValue(isoNumber, kCFNumberDoubleType, &iso))
                result.iso = iso;
        }
    }
    const auto tiff = properties.get() ? static_cast<CFDictionaryRef>(CFDictionaryGetValue(
                                             properties.get(), kCGImagePropertyTIFFDictionary))
                                       : nullptr;
    result.cameraMake = string(tiff, kCGImagePropertyTIFFMake);
    result.cameraModel = string(tiff, kCGImagePropertyTIFFModel);
    std::array<std::uint64_t,
               ImageMeasurement::fingerprintWidth * ImageMeasurement::fingerprintHeight>
        fingerprintSums{};
    std::array<std::uint64_t,
               ImageMeasurement::fingerprintWidth * ImageMeasurement::fingerprintHeight>
        fingerprintCounts{};
    for (std::size_t y = 0; y < height; ++y)
        for (std::size_t x = 0; x < width; ++x) {
            const std::size_t fingerprintX =
                std::min(ImageMeasurement::fingerprintWidth - 1,
                         x * ImageMeasurement::fingerprintWidth / width);
            const std::size_t fingerprintY =
                std::min(ImageMeasurement::fingerprintHeight - 1,
                         y * ImageMeasurement::fingerprintHeight / height);
            const std::size_t fingerprintIndex =
                fingerprintY * ImageMeasurement::fingerprintWidth + fingerprintX;
            fingerprintSums[fingerprintIndex] += pixels[y * width + x];
            ++fingerprintCounts[fingerprintIndex];
        }
    for (std::size_t index = 0; index < result.appearanceFingerprint.size(); ++index)
        if (fingerprintCounts[index] > 0)
            result.appearanceFingerprint[index] =
                static_cast<std::uint8_t>(fingerprintSums[index] / fingerprintCounts[index]);
    return result;
}
} // namespace

bool CaptureReport::valid() const {
    return std::none_of(issues.begin(), issues.end(), [](const auto& issue) {
        return issue.severity == CaptureIssue::Severity::error;
    });
}

CaptureReport validateCapture(const std::filesystem::path& input,
                              const ValidationOptions& options) {
    CaptureReport report;
    report.root = input;
    if (!std::filesystem::is_directory(input)) {
        report.issues.push_back({CaptureIssue::Severity::error, "not-a-directory",
                                 "Capture input must be a readable directory", input});
        return report;
    }

    std::vector<std::filesystem::path> candidates;
    std::error_code traversalError;
    std::filesystem::recursive_directory_iterator iterator(
        input, std::filesystem::directory_options::skip_permission_denied, traversalError);
    const std::filesystem::recursive_directory_iterator end;
    while (!traversalError && iterator != end) {
        std::error_code entryError;
        if (iterator->is_regular_file(entryError) && !entryError && supported(iterator->path()))
            candidates.push_back(iterator->path());
        iterator.increment(traversalError);
    }
    if (traversalError)
        report.issues.push_back({CaptureIssue::Severity::error, "directory-read-failed",
                                 "The capture directory could not be read completely", input});
    std::sort(candidates.begin(), candidates.end());
    for (const auto& path : candidates) {
        if (auto image = measure(path, options.analysisMaximumDimension)) {
            report.sourceBytes += image->fileBytes;
            report.images.push_back(std::move(*image));
        } else {
            report.issues.push_back({CaptureIssue::Severity::error, "image-decode-failed",
                                     "ImageIO could not decode a complete image", path});
        }
    }
    if (report.images.size() < options.minimumImages) {
        report.issues.push_back(
            {CaptureIssue::Severity::error, "insufficient-images",
             "At least " + std::to_string(options.minimumImages) + " decodable images are required",
             std::nullopt});
    }
    for (const auto& image : report.images) {
        constexpr std::uint64_t workingBytesPerPixel = 16;
        const auto pixels =
            static_cast<std::uint64_t>(image.width) * static_cast<std::uint64_t>(image.height);
        report.estimatedWorkingBytes += pixels * workingBytesPerPixel;
    }
    if (report.images.empty())
        return report;

    std::vector<double> sharpness;
    sharpness.reserve(report.images.size());
    for (const auto& image : report.images)
        sharpness.push_back(image.sharpness);
    std::sort(sharpness.begin(), sharpness.end());
    report.medianSharpness = sharpness[sharpness.size() / 2];
    if (report.medianSharpness > 0.0) {
        for (const auto& image : report.images) {
            if (image.sharpness < report.medianSharpness * options.relativeBlurWarning)
                report.issues.push_back({CaptureIssue::Severity::warning, "relative-blur",
                                         "Sharpness is far below the capture median", image.path});
        }
    }

    auto [minimum, maximum] = std::minmax_element(
        report.images.begin(), report.images.end(),
        [](const auto& a, const auto& b) { return a.meanLuminance < b.meanLuminance; });
    constexpr double epsilon = 1.0 / 255.0;
    report.exposureSpreadStops =
        std::log2((maximum->meanLuminance + epsilon) / (minimum->meanLuminance + epsilon));
    if (report.exposureSpreadStops > options.exposureSpreadWarningStops)
        report.issues.push_back({CaptureIssue::Severity::warning, "exposure-spread",
                                 "Image luminance spread exceeds the configured stop threshold",
                                 std::nullopt});
    return report;
}

} // namespace aether::capture
