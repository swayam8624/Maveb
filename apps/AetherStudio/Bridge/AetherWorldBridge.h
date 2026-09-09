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
- (NSData* _Nullable)latestEntitiesJSONWithError:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)translateEntity:(uint64_t)entityId
                                   x:(float)x
                                   y:(float)y
                                   z:(float)z
                timestampNanoseconds:(uint64_t)timestampNanoseconds
                               error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)relabelEntity:(uint64_t)entityId
                     semanticLabel:(NSString*)semanticLabel
              timestampNanoseconds:(uint64_t)timestampNanoseconds
                             error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)removeEntity:(uint64_t)entityId
             timestampNanoseconds:(uint64_t)timestampNanoseconds
                            error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)revertToRevision:(uint64_t)sourceRevision
                 timestampNanoseconds:(uint64_t)timestampNanoseconds
                                error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)semanticEntities:(NSString*)semanticLabel
                           maxResults:(NSUInteger)maxResults
                                error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)nearestEntitiesFromX:(float)x
                                        y:(float)y
                                        z:(float)z
                            semanticLabel:(NSString*)semanticLabel
                   maximumDistanceMeters:(float)maximumDistanceMeters
                               maxResults:(NSUInteger)maxResults
                                    error:(NSError* _Nullable* _Nullable)error;
- (NSData* _Nullable)relationsFromEntity:(uint64_t)subjectId
                                toEntity:(uint64_t)referenceId
                      nearDistanceMeters:(float)nearDistanceMeters
                                   error:(NSError* _Nullable* _Nullable)error;

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
FOUNDATION_EXPORT NSData* _Nullable AetherWorldLatestEntitiesJSON(
    AetherWorldBridge* bridge, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldTranslateEntity(
    AetherWorldBridge* bridge, uint64_t entityId, float x, float y, float z,
    uint64_t timestampNanoseconds, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldRelabelEntity(
    AetherWorldBridge* bridge, uint64_t entityId, NSString* semanticLabel,
    uint64_t timestampNanoseconds, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldRemoveEntity(
    AetherWorldBridge* bridge, uint64_t entityId, uint64_t timestampNanoseconds,
    NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldRevertToRevision(
    AetherWorldBridge* bridge, uint64_t sourceRevision, uint64_t timestampNanoseconds,
    NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldSemanticEntities(
    AetherWorldBridge* bridge, NSString* semanticLabel, NSUInteger maxResults,
    NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldNearestEntities(
    AetherWorldBridge* bridge, float x, float y, float z, NSString* semanticLabel,
    float maximumDistanceMeters, NSUInteger maxResults, NSError* _Nullable* _Nullable error);
FOUNDATION_EXPORT NSData* _Nullable AetherWorldRelations(
    AetherWorldBridge* bridge, uint64_t subjectId, uint64_t referenceId, float nearDistanceMeters,
    NSError* _Nullable* _Nullable error);

NS_ASSUME_NONNULL_END
