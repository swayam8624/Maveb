#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN

/// Live captured-reality viewport whose native state keeps the persistent world, editable Gaussian
/// field, entity ownership, and Metal renderer synchronized.
@interface AetherPersistentGaussianView : NSView
@property(nonatomic) NSInteger preferredFramesPerSecond;
@property(nonatomic, readonly, copy) NSString* rendererStatus;

/// Loads an append-only world archive. If durable Gaussian/ownership sidecars already exist beside
/// the archive, they are restored automatically into the live renderer.
- (BOOL)loadWorldArchiveAtURL:(NSURL*)archiveURL error:(NSError* _Nullable* _Nullable)error;

/// Imports an initial Gaussian PLY for the loaded world, assigns stable entity ownership, and makes
/// it the live captured scene. Subsequent saves use deterministic sidecars beside the world archive.
- (BOOL)loadGaussianPLYAtURL:(NSURL*)plyURL error:(NSError* _Nullable* _Nullable)error;

/// Persists the current world revision chain, edited Gaussian field, and ownership map.
- (BOOL)savePersistentStateWithError:(NSError* _Nullable* _Nullable)error;

/// JSON payloads used by SwiftUI without exposing C++ ABI types.
- (NSData* _Nullable)entitiesJSONWithError:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)ownershipJSONWithError:(NSError* _Nullable* _Nullable)error;

/// Moves one stable persistent entity and all Gaussian primitives owned by it. The GPU subset is
/// preflighted before the World+CPU-Gaussian transaction commits, then published to Metal only after
/// all engine invariants pass.
- (NSData* _Nullable)translateEntity:(uint64_t)entityId
                                   x:(float)x
                                   y:(float)y
                                   z:(float)z
                timestampNanoseconds:(uint64_t)timestampNanoseconds
                               error:(NSError* _Nullable* _Nullable)error;
@end

/// Exact C entry points keep Swift 6 independent from Objective-C selector import heuristics.
FOUNDATION_EXPORT BOOL AetherPersistentLoadWorld(
    AetherPersistentGaussianView* view, NSURL* archiveURL, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT BOOL AetherPersistentLoadGaussianPLY(
    AetherPersistentGaussianView* view, NSURL* plyURL, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT BOOL AetherPersistentSaveState(
    AetherPersistentGaussianView* view, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherPersistentEntitiesJSON(
    AetherPersistentGaussianView* view, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherPersistentOwnershipJSON(
    AetherPersistentGaussianView* view, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherPersistentTranslateEntity(
    AetherPersistentGaussianView* view, uint64_t entityId, float x, float y, float z,
    uint64_t timestampNanoseconds, NSError* _Nullable* _Nullable error);

NS_ASSUME_NONNULL_END
