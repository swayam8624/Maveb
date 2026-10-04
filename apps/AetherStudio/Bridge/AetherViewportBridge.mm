#import "AetherViewportBridge.h"

#import <Metal/Metal.h>
#import <MetalKit/MetalKit.h>

#include <aether/core/Diagnostics.hpp>
#include <aether/core/Log.hpp>
#include <aether/metal/Renderer.hpp>

#include <algorithm>
#include <memory>

static NSString* gAetherRendererStatus = @"Renderer has not been initialized";

@interface AetherViewportDelegate : NSObject <MTKViewDelegate>
- (instancetype)initWithDevice:(id<MTLDevice>)device;
- (NSArray<NSString*>*)loadSceneAtPath:(NSString*)path;
- (nullable NSArray<NSString*>*)attachDynamicMeshAtPath:(NSString*)path;
- (void)detachDynamicMesh;
- (void)setCameraKey:(unichar)key active:(BOOL)active;
- (void)addCameraLookX:(CGFloat)x y:(CGFloat)y;
- (void)addCameraDolly:(CGFloat)amount;
- (void)clearCameraMovement;
- (NSInteger)pickGaussianX:(NSUInteger)x y:(NSUInteger)y;
- (NSInteger)pickMeshX:(NSUInteger)x y:(NSUInteger)y;
- (void)setGaussianDebugMode:(NSInteger)mode;
- (void)setShadowDebugMode:(NSInteger)mode slice:(NSInteger)slice;
- (void)setExposureStops:(float)stops;
- (NSArray<NSNumber*>*)meshTransformForEntity:(NSInteger)entityId;
- (BOOL)setMeshTransformForEntity:(NSInteger)entityId values:(NSArray<NSNumber*>*)values;
- (BOOL)clearMeshTransformForEntity:(NSInteger)entityId;
- (NSArray<NSString*>*)materialNames;
- (NSArray<NSNumber*>*)materialForId:(NSInteger)materialId;
- (BOOL)setMaterialForId:(NSInteger)materialId values:(NSArray<NSNumber*>*)values;
- (BOOL)clearMaterialForId:(NSInteger)materialId;
- (BOOL)replaceLights:(NSArray<NSArray<NSNumber*>*>*)lights;
- (BOOL)setSelectedMeshEntity:(NSInteger)entityId;
- (NSInteger)pickGizmoAxisX:(NSUInteger)x y:(NSUInteger)y;
- (NSArray<NSNumber*>*)translateSelectedAxis:(NSInteger)axis distance:(float)distance;
- (void)setGizmoMode:(NSInteger)mode;
- (NSArray<NSNumber*>*)cameraState;
- (BOOL)setCameraState:(NSArray<NSNumber*>*)values;
- (BOOL)setPlaybackState:(NSArray<NSNumber*>*)values;
- (NSArray<NSNumber*>*)manipulateSelectedAxis:(NSInteger)axis
                                     distance:(float)distance
                                         mode:(NSInteger)mode;
@property(nonatomic, readonly, copy) NSString* rendererStatus;
@end

@implementation AetherViewportDelegate {
    std::unique_ptr<aether::metal::Renderer> _renderer;
    NSString* _rendererStatus;
}

- (NSArray<NSNumber*>*)cameraState {
    if (!_renderer)
        return @[];
    const auto camera = _renderer->cameraSnapshot();
    return @[
        @(camera.position.x), @(camera.position.y), @(camera.position.z), @(camera.yaw),
        @(camera.pitch), @(camera.verticalFieldOfViewRadians)
    ];
}

- (BOOL)setCameraState:(NSArray<NSNumber*>*)values {
    if (!_renderer || values.count != 6)
        return NO;
    aether::metal::CameraSnapshot camera;
    camera.position = {values[0].floatValue, values[1].floatValue, values[2].floatValue};
    camera.yaw = values[3].floatValue;
    camera.pitch = values[4].floatValue;
    camera.verticalFieldOfViewRadians = values[5].floatValue;
    return _renderer->setCameraSnapshot(camera).has_value();
}

- (BOOL)setPlaybackState:(NSArray<NSNumber*>*)values {
    if (!_renderer || values.count != 4)
        return NO;
    const NSInteger clip = values[0].integerValue;
    const std::optional<std::size_t> clipIndex =
        clip < 0 ? std::nullopt : std::optional<std::size_t>{static_cast<std::size_t>(clip)};
    return _renderer
        ->setAnimationPlayback(clipIndex, values[1].floatValue, values[2].boolValue,
                               values[3].boolValue)
        .has_value();
}

- (instancetype)initWithDevice:(id<MTLDevice>)device {
    self = [super init];
    if (self) {
        auto result =
            aether::metal::Renderer::create(reinterpret_cast<MTL::Device*>((__bridge void*)device));
        if (result) {
            _renderer = std::move(*result);
            const auto& capabilities = _renderer->capabilities();
            _rendererStatus =
                [NSString stringWithFormat:@"%s · Apple GPU family %u", capabilities.name.c_str(),
                                           capabilities.highestAppleFamily];
            NSLog(@"AETHER renderer initialized: %@", _rendererStatus);
        } else {
            _rendererStatus = [NSString stringWithUTF8String:result.error().describe().c_str()];
            aether::Log::instance().write(aether::LogLevel::error, result.error().describe());
            NSLog(@"AETHER renderer initialization failed: %@", _rendererStatus);
        }
        gAetherRendererStatus = _rendererStatus;
    }
    return self;
}

- (NSString*)rendererStatus {
    return _rendererStatus;
}

- (void)drawInMTKView:(MTKView*)view {
    if (_renderer) {
        _renderer->draw(reinterpret_cast<MTK::View*>((__bridge void*)view));
    }
}

- (void)mtkView:(MTKView*)view drawableSizeWillChange:(CGSize)size {
    (void)view;
    if (_renderer) {
        _renderer->drawableSizeWillChange(size);
    }
}

- (NSArray<NSString*>*)loadSceneAtPath:(NSString*)path {
    if (!_renderer) {
        return @[];
    }
    const NSString* extension = path.pathExtension.lowercaseString;
    aether::Result<void> result;
    if ([extension isEqualToString:@"ply"]) {
        result = _renderer->loadPly(path.fileSystemRepresentation);
    } else if ([extension isEqualToString:@"aether"]) {
        result = _renderer->loadAether(path.fileSystemRepresentation);
    } else {
        result = _renderer->loadGltf(path.fileSystemRepresentation);
    }
    if (!result) {
        NSLog(@"AETHER scene load failed: %s", result.error().describe().c_str());
        return @[];
    } else {
        NSLog(@"AETHER scene load succeeded: %@", path.lastPathComponent);
    }
    NSMutableArray<NSString*>* names = [NSMutableArray array];
    for (const auto& name : _renderer->meshEntityNames())
        [names addObject:[NSString stringWithUTF8String:name.c_str()]];
    return names;
}

- (nullable NSArray<NSString*>*)attachDynamicMeshAtPath:(NSString*)path {
    if (!_renderer)
        return nil;
    const auto result = _renderer->attachDynamicGltf(path.fileSystemRepresentation);
    if (!result) {
        NSLog(@"AETHER dynamic mesh attach failed: %s", result.error().describe().c_str());
        return nil;
    }
    NSMutableArray<NSString*>* names = [NSMutableArray array];
    for (const auto& name : _renderer->meshEntityNames())
        [names addObject:[NSString stringWithUTF8String:name.c_str()]];
    NSLog(@"AETHER dynamic mesh attached: %@", path.lastPathComponent);
    return names;
}

- (void)detachDynamicMesh {
    if (_renderer)
        _renderer->detachDynamicGltf();
}

- (void)setCameraKey:(unichar)key active:(BOOL)active {
    if (!_renderer)
        return;
    switch (key) {
    case 'w':
        _renderer->setCameraMovement(aether::scene::CameraMove::forward, active);
        break;
    case 's':
        _renderer->setCameraMovement(aether::scene::CameraMove::backward, active);
        break;
    case 'a':
        _renderer->setCameraMovement(aether::scene::CameraMove::left, active);
        break;
    case 'd':
        _renderer->setCameraMovement(aether::scene::CameraMove::right, active);
        break;
    case 'e':
        _renderer->setCameraMovement(aether::scene::CameraMove::up, active);
        break;
    case 'q':
        _renderer->setCameraMovement(aether::scene::CameraMove::down, active);
        break;
    default:
        break;
    }
}

- (void)addCameraLookX:(CGFloat)x y:(CGFloat)y {
    if (_renderer) {
        _renderer->addCameraLookDelta(static_cast<float>(x), static_cast<float>(y));
    }
}

- (void)addCameraDolly:(CGFloat)amount {
    if (_renderer) {
        _renderer->addCameraDolly(static_cast<float>(amount));
    }
}

- (void)clearCameraMovement {
    if (_renderer)
        _renderer->clearCameraMovement();
}

- (NSInteger)pickGaussianX:(NSUInteger)x y:(NSUInteger)y {
    if (!_renderer)
        return 0;
    const auto result =
        _renderer->pickGaussian(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y));
    if (!result) {
        NSLog(@"AETHER Gaussian pick failed: %s", result.error().describe().c_str());
        return 0;
    }
    return static_cast<NSInteger>(*result);
}

- (NSInteger)pickMeshX:(NSUInteger)x y:(NSUInteger)y {
    if (!_renderer)
        return 0;
    const auto result =
        _renderer->pickMesh(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y));
    if (!result) {
        NSLog(@"AETHER mesh pick failed: %s", result.error().describe().c_str());
        return 0;
    }
    return static_cast<NSInteger>(*result);
}

- (void)setGaussianDebugMode:(NSInteger)mode {
    if (_renderer)
        _renderer->setGaussianDebugMode(static_cast<std::uint32_t>(MAX(0, mode)));
}

- (void)setShadowDebugMode:(NSInteger)mode slice:(NSInteger)slice {
    if (_renderer)
        _renderer->setShadowDebugMode(static_cast<std::uint32_t>(MAX(0, mode)),
                                      static_cast<std::uint32_t>(MAX(0, slice)));
}

- (void)setExposureStops:(float)stops {
    if (_renderer)
        _renderer->setExposureStops(stops);
}

- (NSArray<NSNumber*>*)meshTransformForEntity:(NSInteger)entityId {
    if (!_renderer || entityId <= 0)
        return nil;
    const auto snapshot = _renderer->meshEntitySnapshot(static_cast<std::uint32_t>(entityId));
    if (!snapshot) {
        NSLog(@"AETHER entity snapshot failed: %s", snapshot.error().describe().c_str());
        return nil;
    }
    const auto& transform = snapshot->worldTransform;
    const simd_float4 rotation = transform.rotation.vector;
    return @[
        @(transform.translation.x), @(transform.translation.y), @(transform.translation.z),
        @(rotation.x), @(rotation.y), @(rotation.z), @(rotation.w), @(transform.scale.x),
        @(transform.scale.y), @(transform.scale.z), @(snapshot->overridden)
    ];
}

- (BOOL)setMeshTransformForEntity:(NSInteger)entityId values:(NSArray<NSNumber*>*)values {
    if (!_renderer || entityId <= 0 || values.count != 10)
        return NO;
    aether::scene::Transform transform;
    transform.translation = {values[0].floatValue, values[1].floatValue, values[2].floatValue};
    transform.rotation = simd_quaternion(values[3].floatValue, values[4].floatValue,
                                         values[5].floatValue, values[6].floatValue);
    transform.scale = {values[7].floatValue, values[8].floatValue, values[9].floatValue};
    const auto result =
        _renderer->setMeshEntityTransform(static_cast<std::uint32_t>(entityId), transform);
    if (!result)
        NSLog(@"AETHER entity transform failed: %s", result.error().describe().c_str());
    return result.has_value();
}

- (BOOL)clearMeshTransformForEntity:(NSInteger)entityId {
    if (!_renderer || entityId <= 0)
        return NO;
    const auto result = _renderer->clearMeshEntityTransform(static_cast<std::uint32_t>(entityId));
    if (!result)
        NSLog(@"AETHER entity transform reset failed: %s", result.error().describe().c_str());
    return result.has_value();
}

- (NSArray<NSString*>*)materialNames {
    NSMutableArray<NSString*>* names = [NSMutableArray array];
    if (!_renderer)
        return names;
    for (const auto& material : _renderer->materialSnapshots())
        [names addObject:[NSString stringWithUTF8String:material.name.c_str()]];
    return names;
}

- (NSArray<NSNumber*>*)materialForId:(NSInteger)materialId {
    if (!_renderer || materialId <= 0)
        return nil;
    const auto materials = _renderer->materialSnapshots();
    if (static_cast<std::size_t>(materialId) > materials.size())
        return nil;
    const auto& material = materials[static_cast<std::size_t>(materialId - 1)];
    return @[
        @(material.baseColor.x), @(material.baseColor.y), @(material.baseColor.z),
        @(material.baseColor.w), @(material.emissive.x), @(material.emissive.y),
        @(material.emissive.z), @(material.metallic), @(material.roughness),
        @(material.normalScale), @(material.occlusionStrength), @(material.alphaCutoff),
        @(material.overridden)
    ];
}

- (BOOL)setMaterialForId:(NSInteger)materialId values:(NSArray<NSNumber*>*)values {
    if (!_renderer || materialId <= 0 || values.count != 12)
        return NO;
    aether::metal::MaterialSnapshot material;
    material.id = static_cast<std::uint32_t>(materialId);
    material.baseColor = {values[0].floatValue, values[1].floatValue, values[2].floatValue,
                          values[3].floatValue};
    material.emissive = {values[4].floatValue, values[5].floatValue, values[6].floatValue};
    material.metallic = values[7].floatValue;
    material.roughness = values[8].floatValue;
    material.normalScale = values[9].floatValue;
    material.occlusionStrength = values[10].floatValue;
    material.alphaCutoff = values[11].floatValue;
    const auto result = _renderer->setMaterialOverride(material);
    if (!result)
        NSLog(@"AETHER material override failed: %s", result.error().describe().c_str());
    return result.has_value();
}

- (BOOL)clearMaterialForId:(NSInteger)materialId {
    if (!_renderer || materialId <= 0)
        return NO;
    const auto result = _renderer->clearMaterialOverride(static_cast<std::uint32_t>(materialId));
    if (!result)
        NSLog(@"AETHER material reset failed: %s", result.error().describe().c_str());
    return result.has_value();
}

- (BOOL)replaceLights:(NSArray<NSArray<NSNumber*>*>*)lights {
    if (!_renderer || lights.count == 0 || lights.count > 4096)
        return NO;
    std::vector<aether::scene::Light> replacements;
    replacements.reserve(lights.count);
    for (NSArray<NSNumber*>* values in lights) {
        if (values.count != 14)
            return NO;
        const NSInteger type = values[0].integerValue;
        if (type < 0 || type > 2)
            return NO;
        aether::scene::Light light;
        light.type = static_cast<aether::scene::LightType>(type);
        light.position = {values[1].floatValue, values[2].floatValue, values[3].floatValue};
        light.range = values[4].floatValue;
        light.direction = {values[5].floatValue, values[6].floatValue, values[7].floatValue};
        light.color = {values[8].floatValue, values[9].floatValue, values[10].floatValue};
        light.intensity = values[11].floatValue;
        light.innerConeRadians = values[12].floatValue;
        light.outerConeRadians = values[13].floatValue;
        replacements.push_back(light);
    }
    const auto result = _renderer->setLights(std::move(replacements));
    if (!result)
        NSLog(@"AETHER light replacement failed: %s", result.error().describe().c_str());
    return result.has_value();
}

- (BOOL)setSelectedMeshEntity:(NSInteger)entityId {
    if (!_renderer || entityId < 0)
        return NO;
    return _renderer->setSelectedMeshEntity(static_cast<std::uint32_t>(entityId)).has_value();
}

- (NSInteger)pickGizmoAxisX:(NSUInteger)x y:(NSUInteger)y {
    if (!_renderer)
        return 0;
    const auto result =
        _renderer->pickGizmoAxis(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y));
    return result ? static_cast<NSInteger>(*result) : 0;
}

- (NSArray<NSNumber*>*)translateSelectedAxis:(NSInteger)axis distance:(float)distance {
    if (!_renderer || axis < 1 || axis > 3)
        return nil;
    const auto result =
        _renderer->translateSelectedMeshPixels(static_cast<std::uint32_t>(axis), distance);
    if (!result)
        return nil;
    const auto& transform = result->worldTransform;
    const simd_float4 rotation = transform.rotation.vector;
    return @[
        @(result->id), @(transform.translation.x), @(transform.translation.y),
        @(transform.translation.z), @(rotation.x), @(rotation.y), @(rotation.z), @(rotation.w),
        @(transform.scale.x), @(transform.scale.y), @(transform.scale.z)
    ];
}

- (void)setGizmoMode:(NSInteger)mode {
    if (_renderer)
        _renderer->setGizmoMode(static_cast<std::uint32_t>(std::clamp(mode, 0L, 2L)));
}

- (NSArray<NSNumber*>*)manipulateSelectedAxis:(NSInteger)axis
                                     distance:(float)distance
                                         mode:(NSInteger)mode {
    if (!_renderer || axis < 1 || axis > 3)
        return nil;
    aether::Result<aether::metal::MeshEntitySnapshot> result =
        mode == 1 ? _renderer->rotateSelectedMeshPixels(static_cast<std::uint32_t>(axis), distance)
        : mode == 2
            ? _renderer->scaleSelectedMeshPixels(static_cast<std::uint32_t>(axis), distance)
            : _renderer->translateSelectedMeshPixels(static_cast<std::uint32_t>(axis), distance);
    if (!result)
        return nil;
    const auto& transform = result->worldTransform;
    const simd_float4 rotation = transform.rotation.vector;
    return @[
        @(result->id), @(transform.translation.x), @(transform.translation.y),
        @(transform.translation.z), @(rotation.x), @(rotation.y), @(rotation.z), @(rotation.w),
        @(transform.scale.x), @(transform.scale.y), @(transform.scale.z)
    ];
}
@end

BOOL AetherWriteDiagnostics(NSURL* destination, NSError** error) {
    if (!destination.isFileURL) {
        if (error) {
            *error = [NSError
                errorWithDomain:@"com.swayamsingal.aether.diagnostics"
                           code:1
                       userInfo:@{NSLocalizedDescriptionKey : @"Destination must be a file URL"}];
        }
        return NO;
    }
    const aether::DiagnosticsContext context{
        "0.1.0", {{"renderer", gAetherRendererStatus.UTF8String ?: "unknown"}}};
    const auto result =
        aether::Diagnostics::writeReport(destination.fileSystemRepresentation, context);
    if (!result) {
        if (error) {
            *error = [NSError errorWithDomain:@"com.swayamsingal.aether.diagnostics"
                                         code:2
                                     userInfo:@{
                                         NSLocalizedDescriptionKey : [NSString
                                             stringWithUTF8String:result.error().describe().c_str()]
                                     }];
        }
        return NO;
    }
    return YES;
}

@implementation AetherViewportView {
    MTKView* _metalView;
    AetherViewportDelegate* _rendererDelegate;
    NSString* _scenePath;
    NSString* _dynamicMeshPath;
    NSInteger _gaussianDebugMode;
    NSInteger _shadowDebugMode;
    NSInteger _shadowDebugSlice;
    float _exposureStops;
    NSInteger _selectedMeshEntity;
    NSInteger _activeGizmoAxis;
    NSInteger _gizmoMode;
}

- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        _metalView = [[MTKView alloc] initWithFrame:self.bounds device:device];
        _metalView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        _metalView.colorPixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
        _metalView.depthStencilPixelFormat = MTLPixelFormatDepth32Float;
        _metalView.framebufferOnly = NO;
        _metalView.clearDepth = 0.0;
        _metalView.clearColor = MTLClearColorMake(0.018, 0.022, 0.030, 1.0);
        _metalView.preferredFramesPerSecond = 60;
        _metalView.enableSetNeedsDisplay = NO;
        _metalView.paused = NO;

        _rendererDelegate = [[AetherViewportDelegate alloc] initWithDevice:device];
        _metalView.delegate = _rendererDelegate;
        [self addSubview:_metalView];
    }
    return self;
}

- (BOOL)acceptsFirstResponder {
    return YES;
}

- (void)viewDidMoveToWindow {
    [super viewDidMoveToWindow];
    [self.window makeFirstResponder:self];
}

- (void)viewWillMoveToWindow:(NSWindow*)newWindow {
    if (!newWindow)
        [_rendererDelegate clearCameraMovement];
    [super viewWillMoveToWindow:newWindow];
}

- (void)keyDown:(NSEvent*)event {
    NSString* characters = event.charactersIgnoringModifiers.lowercaseString;
    if (characters.length > 0) {
        [_rendererDelegate setCameraKey:[characters characterAtIndex:0] active:YES];
    } else {
        [super keyDown:event];
    }
}

- (void)keyUp:(NSEvent*)event {
    NSString* characters = event.charactersIgnoringModifiers.lowercaseString;
    if (characters.length > 0) {
        [_rendererDelegate setCameraKey:[characters characterAtIndex:0] active:NO];
        if (self.onCameraChanged)
            self.onCameraChanged([_rendererDelegate cameraState]);
    } else {
        [super keyUp:event];
    }
}

- (void)rightMouseDown:(NSEvent*)event {
    [self.window makeFirstResponder:self];
    [super rightMouseDown:event];
}

- (void)mouseDown:(NSEvent*)event {
    [self.window makeFirstResponder:self];
    const NSPoint local = [self convertPoint:event.locationInWindow fromView:nil];
    const NSPoint backing = [self convertPointToBacking:local];
    const NSUInteger width = static_cast<NSUInteger>(_metalView.drawableSize.width);
    const NSUInteger height = static_cast<NSUInteger>(_metalView.drawableSize.height);
    if (width == 0 || height == 0)
        return;
    const NSUInteger x =
        static_cast<NSUInteger>(std::clamp(backing.x, 0.0, static_cast<double>(width - 1)));
    const double topOriginY = static_cast<double>(height) - 1.0 - backing.y;
    const NSUInteger y =
        static_cast<NSUInteger>(std::clamp(topOriginY, 0.0, static_cast<double>(height - 1)));
    const NSInteger gizmoAxis = [_rendererDelegate pickGizmoAxisX:x y:y];
    if (_selectedMeshEntity > 0 && gizmoAxis > 0) {
        _activeGizmoAxis = gizmoAxis;
        return;
    }
    const NSString* sceneExtension = _scenePath.pathExtension.lowercaseString;
    const BOOL gaussian =
        [sceneExtension isEqualToString:@"ply"] || [sceneExtension isEqualToString:@"aether"];
    NSInteger entityId = [_rendererDelegate pickMeshX:x y:y];
    BOOL pickedGaussian = NO;
    if (entityId == 0 && gaussian) {
        entityId = [_rendererDelegate pickGaussianX:x y:y];
        pickedGaussian = entityId != 0;
    }
    if (self.onEntityPicked)
        self.onEntityPicked(entityId, pickedGaussian);
}

- (void)mouseDragged:(NSEvent*)event {
    if (_activeGizmoAxis == 0) {
        [super mouseDragged:event];
        return;
    }
    float distance = 0.0F;
    if (_activeGizmoAxis == 1)
        distance = static_cast<float>(event.deltaX);
    else if (_activeGizmoAxis == 2)
        distance = static_cast<float>(-event.deltaY);
    else
        distance = static_cast<float>(event.deltaX - event.deltaY) * 0.7F;
    NSArray<NSNumber*>* values = [_rendererDelegate manipulateSelectedAxis:_activeGizmoAxis
                                                                  distance:distance
                                                                      mode:_gizmoMode];
    if (values.count == 11 && self.onMeshTransformEdited)
        self.onMeshTransformEdited(values[0].integerValue,
                                   [values subarrayWithRange:NSMakeRange(1, 10)]);
}

- (void)mouseUp:(NSEvent*)event {
    _activeGizmoAxis = 0;
    [super mouseUp:event];
}

- (void)rightMouseDragged:(NSEvent*)event {
    [_rendererDelegate addCameraLookX:event.deltaX y:event.deltaY];
    if (self.onCameraChanged)
        self.onCameraChanged([_rendererDelegate cameraState]);
}

- (void)scrollWheel:(NSEvent*)event {
    [_rendererDelegate addCameraDolly:event.scrollingDeltaY];
    if (self.onCameraChanged)
        self.onCameraChanged([_rendererDelegate cameraState]);
}

- (NSString*)rendererStatus {
    return _rendererDelegate.rendererStatus;
}

- (NSInteger)preferredFramesPerSecond {
    return _metalView.preferredFramesPerSecond;
}

- (void)setPreferredFramesPerSecond:(NSInteger)value {
    _metalView.preferredFramesPerSecond = MAX(1, value);
}

- (NSInteger)gaussianDebugMode {
    return _gaussianDebugMode;
}

- (void)setGaussianDebugMode:(NSInteger)value {
    _gaussianDebugMode = value;
    [_rendererDelegate setGaussianDebugMode:value];
}

- (NSInteger)shadowDebugMode {
    return _shadowDebugMode;
}
- (void)setShadowDebugMode:(NSInteger)value {
    _shadowDebugMode = std::clamp(value, 0L, 2L);
    [_rendererDelegate setShadowDebugMode:_shadowDebugMode slice:_shadowDebugSlice];
}
- (NSInteger)shadowDebugSlice {
    return _shadowDebugSlice;
}
- (void)setShadowDebugSlice:(NSInteger)value {
    _shadowDebugSlice = MAX(0, value);
    [_rendererDelegate setShadowDebugMode:_shadowDebugMode slice:_shadowDebugSlice];
}

- (float)exposureStops {
    return _exposureStops;
}

- (void)setExposureStops:(float)value {
    _exposureStops = std::clamp(value, -16.0F, 16.0F);
    [_rendererDelegate setExposureStops:_exposureStops];
}

- (NSString*)scenePath {
    return _scenePath;
}

- (void)setScenePath:(NSString*)scenePath {
    if ((_scenePath == scenePath) || [_scenePath isEqualToString:scenePath]) {
        return;
    }
    _scenePath = [scenePath copy];
    _dynamicMeshPath = nil;
    if (_scenePath.length == 0) {
        return;
    }
    NSArray<NSString*>* names = [_rendererDelegate loadSceneAtPath:_scenePath];
    if (self.onMeshEntitiesChanged)
        self.onMeshEntitiesChanged(names);
    if (self.onMaterialsChanged)
        self.onMaterialsChanged([_rendererDelegate materialNames]);
}

- (NSString*)dynamicMeshPath {
    return _dynamicMeshPath;
}

- (void)setDynamicMeshPath:(NSString*)dynamicMeshPath {
    if ((_dynamicMeshPath == dynamicMeshPath) || [_dynamicMeshPath isEqualToString:dynamicMeshPath])
        return;
    if (dynamicMeshPath.length == 0) {
        [_rendererDelegate detachDynamicMesh];
        _dynamicMeshPath = nil;
        if (self.onMeshEntitiesChanged)
            self.onMeshEntitiesChanged(@[]);
        if (self.onMaterialsChanged)
            self.onMaterialsChanged(@[]);
        return;
    }
    NSArray<NSString*>* names = [_rendererDelegate attachDynamicMeshAtPath:dynamicMeshPath];
    if (!names)
        return;
    _dynamicMeshPath = [dynamicMeshPath copy];
    if (self.onMeshEntitiesChanged)
        self.onMeshEntitiesChanged(names);
    if (self.onMaterialsChanged)
        self.onMaterialsChanged([_rendererDelegate materialNames]);
}

- (NSArray<NSNumber*>*)meshTransformForEntity:(NSInteger)entityId {
    return [_rendererDelegate meshTransformForEntity:entityId];
}

- (BOOL)setMeshTransformForEntity:(NSInteger)entityId values:(NSArray<NSNumber*>*)values {
    return [_rendererDelegate setMeshTransformForEntity:entityId values:values];
}

- (BOOL)clearMeshTransformForEntity:(NSInteger)entityId {
    return [_rendererDelegate clearMeshTransformForEntity:entityId];
}

- (NSArray<NSNumber*>*)materialForId:(NSInteger)materialId {
    return [_rendererDelegate materialForId:materialId];
}

- (BOOL)setMaterialForId:(NSInteger)materialId values:(NSArray<NSNumber*>*)values {
    return [_rendererDelegate setMaterialForId:materialId values:values];
}

- (BOOL)clearMaterialForId:(NSInteger)materialId {
    return [_rendererDelegate clearMaterialForId:materialId];
}

- (BOOL)replaceLights:(NSArray<NSArray<NSNumber*>*>*)lights {
    return [_rendererDelegate replaceLights:lights];
}

- (NSInteger)selectedMeshEntity {
    return _selectedMeshEntity;
}

- (NSInteger)gizmoMode {
    return _gizmoMode;
}
- (void)setGizmoMode:(NSInteger)value {
    _gizmoMode = std::clamp(value, 0L, 2L);
    [_rendererDelegate setGizmoMode:_gizmoMode];
}

- (NSArray<NSNumber*>*)cameraState {
    return [_rendererDelegate cameraState];
}
- (void)setCameraState:(NSArray<NSNumber*>*)values {
    [_rendererDelegate setCameraState:values];
}
- (NSArray<NSNumber*>*)playbackState {
    return @[];
}
- (void)setPlaybackState:(NSArray<NSNumber*>*)values {
    [_rendererDelegate setPlaybackState:values];
}

- (void)setSelectedMeshEntity:(NSInteger)entityId {
    _selectedMeshEntity = MAX(0, entityId);
    [_rendererDelegate setSelectedMeshEntity:_selectedMeshEntity];
}
@end
