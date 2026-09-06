#import "AetherViewportPerformance.h"

#import <MetalKit/MetalKit.h>

#include <algorithm>
#include <cmath>

@implementation AetherResponsiveViewportView {
    CGFloat _renderScale;
    NSInteger _configuredFramesPerSecond;
    NSUInteger _interactionGeneration;
    BOOL _interacting;
}

- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        _renderScale = 1.0;
        _configuredFramesPerSecond = 60;
        _interactionGeneration = 0;
        _interacting = NO;
        MTKView* metalView = [self aetherMetalView];
        metalView.autoResizeDrawable = NO;
        [self updateDrawableSize];
    }
    return self;
}

- (MTKView*)aetherMetalView {
    for (NSView* child in self.subviews) {
        if ([child isKindOfClass:MTKView.class])
            return (MTKView*)child;
    }
    return nil;
}

- (BOOL)isGaussianScene {
    NSString* extension = self.scenePath.pathExtension.lowercaseString;
    return [extension isEqualToString:@"ply"] || [extension isEqualToString:@"aether"];
}

- (CGFloat)interactiveRenderScale {
    // Gaussian compositing cost grows rapidly with viewport area/tile coverage. Keep
    // interaction responsive, then immediately recover full-resolution presentation.
    return [self isGaussianScene] ? 0.45 : 0.68;
}

- (void)updateDrawableSize {
    MTKView* metalView = [self aetherMetalView];
    if (!metalView)
        return;

    NSSize backing = [self convertSizeToBacking:self.bounds.size];
    if (backing.width <= 0.0 || backing.height <= 0.0)
        return;

    const CGFloat width = std::max<CGFloat>(1.0, std::floor(backing.width * _renderScale));
    const CGFloat height = std::max<CGFloat>(1.0, std::floor(backing.height * _renderScale));
    const CGSize current = metalView.drawableSize;
    if (std::abs(current.width - width) > 1.0 || std::abs(current.height - height) > 1.0)
        metalView.drawableSize = CGSizeMake(width, height);
}

- (void)applyRenderScale:(CGFloat)scale {
    _renderScale = std::clamp(scale, 0.35, 1.0);
    [self updateDrawableSize];
}

- (void)layout {
    [super layout];
    [self updateDrawableSize];
}

- (void)viewDidMoveToWindow {
    [super viewDidMoveToWindow];
    [self updateDrawableSize];
}

- (NSInteger)preferredFramesPerSecond {
    return _configuredFramesPerSecond;
}

- (void)setPreferredFramesPerSecond:(NSInteger)value {
    _configuredFramesPerSecond = std::clamp<NSInteger>(value, 1, 120);
    NSInteger effective = _interacting ? std::max<NSInteger>(_configuredFramesPerSecond, 60)
                                       : _configuredFramesPerSecond;
    [super setPreferredFramesPerSecond:effective];
}

- (void)beginResponsiveInteraction {
    ++_interactionGeneration;
    _interacting = YES;
    [self applyRenderScale:[self interactiveRenderScale]];
    [super setPreferredFramesPerSecond:std::max<NSInteger>(_configuredFramesPerSecond, 60)];
}

- (void)restoreFullQuality {
    ++_interactionGeneration;
    _interacting = NO;
    [self applyRenderScale:1.0];
    [super setPreferredFramesPerSecond:_configuredFramesPerSecond];
}

- (void)scheduleFullQualityRestore:(NSTimeInterval)delay {
    const NSUInteger generation = _interactionGeneration;
    __weak AetherResponsiveViewportView* weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
                       AetherResponsiveViewportView* strongSelf = weakSelf;
                       if (!strongSelf || strongSelf->_interactionGeneration != generation)
                           return;
                       strongSelf->_interacting = NO;
                       [strongSelf applyRenderScale:1.0];
                       [super setPreferredFramesPerSecond:strongSelf->_configuredFramesPerSecond];
                   });
}

- (void)setScenePath:(NSString*)scenePath {
    MTKView* metalView = [self aetherMetalView];
    const BOOL wasPaused = metalView.paused;
    metalView.paused = YES;
    [self restoreFullQuality];
    [super setScenePath:scenePath];
    metalView.paused = wasPaused;
}

- (void)setDynamicMeshPath:(NSString*)dynamicMeshPath {
    MTKView* metalView = [self aetherMetalView];
    const BOOL wasPaused = metalView.paused;
    metalView.paused = YES;
    [super setDynamicMeshPath:dynamicMeshPath];
    metalView.paused = wasPaused;
}

- (void)keyDown:(NSEvent*)event {
    NSString* characters = event.charactersIgnoringModifiers.lowercaseString;
    if (characters.length > 0) {
        const unichar key = [characters characterAtIndex:0];
        if (key == 'w' || key == 'a' || key == 's' || key == 'd' || key == 'q' || key == 'e')
            [self beginResponsiveInteraction];
    }
    [super keyDown:event];
}

- (void)keyUp:(NSEvent*)event {
    [super keyUp:event];
    [self scheduleFullQualityRestore:0.10];
}

- (void)mouseDown:(NSEvent*)event {
    // Picking uses drawable-space coordinates, so perform the initial hit test at full quality.
    [self restoreFullQuality];
    [super mouseDown:event];
}

- (void)mouseDragged:(NSEvent*)event {
    [self beginResponsiveInteraction];
    [super mouseDragged:event];
    [self scheduleFullQualityRestore:0.14];
}

- (void)rightMouseDragged:(NSEvent*)event {
    [self beginResponsiveInteraction];
    [super rightMouseDragged:event];
    [self scheduleFullQualityRestore:0.14];
}

- (void)scrollWheel:(NSEvent*)event {
    [self beginResponsiveInteraction];
    [super scrollWheel:event];
    [self scheduleFullQualityRestore:0.16];
}

@end
