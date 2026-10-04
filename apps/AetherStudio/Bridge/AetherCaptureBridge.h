#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Runs the native ImageIO capture validator and returns its versioned report as JSON data.
/// The function is synchronous; callers should invoke it away from the main actor.
FOUNDATION_EXPORT NSData* _Nullable AetherValidateCaptureDirectory(
    NSURL* directoryURL, NSError* _Nullable* _Nullable error);

NS_ASSUME_NONNULL_END
