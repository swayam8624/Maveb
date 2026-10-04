#import "AetherCaptureBridge.h"

#include <aether/capture/CaptureValidator.hpp>

namespace {
NSString* text(const std::string& value) {
    return [[NSString alloc] initWithBytes:value.data()
                                   length:value.size()
                                 encoding:NSUTF8StringEncoding] ?: @"";
}
} // namespace

NSData* AetherValidateCaptureDirectory(NSURL* directoryURL, NSError** error) {
    const auto report = aether::capture::validateCapture(directoryURL.fileSystemRepresentation);
    NSMutableArray* images = [NSMutableArray arrayWithCapacity:report.images.size()];
    for (const auto& image : report.images) {
        [images addObject:@{
            @"path": text(image.path.string()), @"bytes": @(image.fileBytes),
            @"width": @(image.width), @"height": @(image.height),
            @"meanLuminance": @(image.meanLuminance),
            @"luminanceDeviation": @(image.luminanceDeviation), @"sharpness": @(image.sharpness),
            @"exposureSeconds": image.exposureSeconds ? @(*image.exposureSeconds) : NSNull.null,
            @"fNumber": image.fNumber ? @(*image.fNumber) : NSNull.null,
            @"iso": image.iso ? @(*image.iso) : NSNull.null,
            @"focalLengthMillimetres": image.focalLengthMillimetres
                ? @(*image.focalLengthMillimetres) : NSNull.null,
            @"cameraMake": text(image.cameraMake), @"cameraModel": text(image.cameraModel)
        }];
    }
    NSMutableArray* issues = [NSMutableArray arrayWithCapacity:report.issues.size()];
    for (const auto& issue : report.issues) {
        [issues addObject:@{
            @"severity": issue.severity == aether::capture::CaptureIssue::Severity::error
                ? @"error" : @"warning",
            @"code": text(issue.code), @"message": text(issue.message),
            @"path": issue.path ? text(issue.path->string()) : NSNull.null
        }];
    }
    NSDictionary* payload = @{
        @"schemaVersion": @1, @"valid": @(report.valid()),
        @"root": text(report.root.string()),
        @"summary": @{
            @"imageCount": @(report.images.size()), @"sourceBytes": @(report.sourceBytes),
            @"estimatedWorkingBytes": @(report.estimatedWorkingBytes),
            @"medianSharpness": @(report.medianSharpness),
            @"exposureSpreadStops": @(report.exposureSpreadStops)
        },
        @"images": images, @"issues": issues
    };
    return [NSJSONSerialization dataWithJSONObject:payload options:0 error:error];
}
