#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Stateful bridge between SwiftUI Studio and the C++ persistent-world engine.
/// Heavy calls are synchronous and must be invoked away from the main actor.
@interface AetherWorldBridge : NSObject {
@private
    void* _worldModel;
}

/// Loads a previously saved persistent-world archive, replacing the bridge's current model.
- (BOOL)loadArchiveAtURL:(NSURL*)archiveURL error:(NSError* _Nullable* _Nullable)error;

/// Atomically saves the complete temporal world history and stable-ID allocator.
- (BOOL)saveArchiveAtURL:(NSURL*)archiveURL error:(NSError* _Nullable* _Nullable)error;

/// Loads a validated canonical reconstruction directory, converts its real mesh instances into
/// persistent observations, associates stable identities, computes Reality Diff/local dirty
/// regions, and commits one new world revision. Returns a compact JSON transaction report.
- (NSData* _Nullable)ingestCanonicalDirectory:(NSURL*)directoryURL
                         timestampNanoseconds:(uint64_t)timestampNanoseconds
                                        error:(NSError* _Nullable* _Nullable)error;

/// Returns compact chronological revision summaries as versioned JSON.
- (NSData* _Nullable)historyJSONWithError:(NSError* _Nullable* _Nullable)error;

/// Returns the latest Reality Diff as versioned JSON. When fewer than two revisions exist,
/// `available` is false rather than treating that state as an error.
- (NSData* _Nullable)latestDiffJSONWithError:(NSError* _Nullable* _Nullable)error;

@end

NS_ASSUME_NONNULL_END
