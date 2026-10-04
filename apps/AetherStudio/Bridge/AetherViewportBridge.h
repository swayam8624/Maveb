#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN

/// AppKit host view that owns the Metal viewport and its C++ renderer.
/// No Metal object is exposed through this Swift-facing API.
@interface AetherViewportView : NSView
@property(nonatomic, readonly, copy) NSString* rendererStatus;
@property(nonatomic) NSInteger preferredFramesPerSecond;
@property(nonatomic, nullable, copy) NSString* scenePath;
@property(nonatomic, nullable, copy) NSString* dynamicMeshPath;
@property(nonatomic, nullable, copy) void (^onEntityPicked)(NSInteger entityId, BOOL gaussian);
@property(nonatomic, nullable, copy) void (^onMeshEntitiesChanged)(NSArray<NSString*>* names);
@property(nonatomic, nullable, copy) void (^onMaterialsChanged)(NSArray<NSString*>* names);
@property(nonatomic, nullable, copy) void (^onMeshTransformEdited)
    (NSInteger entityId, NSArray<NSNumber*>* values);
@property(nonatomic, nullable, copy) void (^onCameraChanged)(NSArray<NSNumber*>* values);
@property(nonatomic) NSInteger selectedMeshEntity;
@property(nonatomic) NSInteger gizmoMode;
@property(nonatomic, copy) NSArray<NSNumber*>* cameraState;
@property(nonatomic, copy) NSArray<NSNumber*>* playbackState;
@property(nonatomic) NSInteger gaussianDebugMode;
@property(nonatomic) NSInteger shadowDebugMode;
@property(nonatomic) NSInteger shadowDebugSlice;
@property(nonatomic) float exposureStops;
- (nullable NSArray<NSNumber*>*)meshTransformForEntity:(NSInteger)entityId;
- (BOOL)setMeshTransformForEntity:(NSInteger)entityId values:(NSArray<NSNumber*>*)values;
- (BOOL)clearMeshTransformForEntity:(NSInteger)entityId;
- (nullable NSArray<NSNumber*>*)materialForId:(NSInteger)materialId;
- (BOOL)setMaterialForId:(NSInteger)materialId values:(NSArray<NSNumber*>*)values;
- (BOOL)clearMaterialForId:(NSInteger)materialId;
- (BOOL)replaceLights:(NSArray<NSArray<NSNumber*>*>*)lights;
@end

/// Writes a privacy-minimized diagnostics JSON file. Returns NO and populates `error` on failure.
FOUNDATION_EXPORT BOOL AetherWriteDiagnostics(NSURL* destination,
                                              NSError* _Nullable* _Nullable error);

NS_ASSUME_NONNULL_END
