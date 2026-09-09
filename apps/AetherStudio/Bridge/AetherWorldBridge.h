#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Stateful bridge between SwiftUI Studio and the C++ persistent-world engine.
/// Heavy calls are synchronous and must be invoked away from the main actor.
@interface AetherWorldBridge : NSObject {
@private
    void* _worldModel;
}

- (BOOL)loadArchiveAtURL:(NSURL*)archiveURL error:(NSError* _Nullable* _Nullable)error;
- (BOOL)saveArchiveAtURL:(NSURL*)archiveURL error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)ingestCanonicalDirectory:(NSURL*)directoryURL
                         timestampNanoseconds:(uint64_t)timestampNanoseconds
                                        error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)historyJSONWithError:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)latestDiffJSONWithError:(NSError* _Nullable* _Nullable)error;

@end

/// Exact C entry points intentionally mirror AetherValidateCaptureDirectory so Swift does not
/// depend on Objective-C selector renaming heuristics.
FOUNDATION_EXPORT BOOL AetherWorldLoadArchive(
    AetherWorldBridge* bridge, NSURL* archiveURL, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT BOOL AetherWorldSaveArchive(
    AetherWorldBridge* bridge, NSURL* archiveURL, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldIngestCanonical(
    AetherWorldBridge* bridge, NSURL* directoryURL, uint64_t timestampNanoseconds,
    NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldHistoryJSON(
    AetherWorldBridge* bridge, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldLatestDiffJSON(
    AetherWorldBridge* bridge, NSError* _Nullable* _Nullable error);

NS_ASSUME_NONNULL_END
