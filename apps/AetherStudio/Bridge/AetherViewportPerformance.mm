#import "AetherViewportPerformance.h"

#import <MetalKit/MetalKit.h>
#import <objc/runtime.h>

#include <aether/metal/GaussianPipeline.hpp>

#include <algorithm>
#include <cmath>

namespace {
char kConfiguredFpsKey;
char kInteractionGenerationKey;
char kInteractingKey;

constexpr std::uint32_t kInteractiveGaussianBudget = 80'000;
constexpr std::uint32_t kSettledGaussianBudget = 240'000;
constexpr NSInteger kInteractionFpsFloor = 45;

void swapInstanceMethods(Class cls, SEL original, SEL replacement) {
    Method originalMethod = class_getInstanceMethod(cls, original);
    Method replacementMethod = class_getInstanceMethod(cls, replacement);
    if (originalMethod && replacementMethod)
        method_exchangeImplementations(originalMethod, replacementMethod);
}
} // namespace

@interface AetherViewportView (AetherPerformance)
- (void)aetherPerf_setPreferredFramesPerSecond:(NSInteger)value;
- (void)aetherPerf_setScenePath:(NSString* _Nullable)scenePath;
- (void)aetherPerf_setDynamicMeshPath:(NSString* _Nullable)dynamicMeshPath;
- (void)aetherPerf_keyDown:(NSEvent*)event;
- (void)aetherPerf_keyUp:(NSEvent*)event;
- (void)aetherPerf_mouseDown:(NSEvent*)event;
- (void)aetherPerf_mouseDragged:(NSEvent*)event;
- (void)aetherPerf_rightMouseDragged:(NSEvent*)event;
- (void)aetherPerf_scrollWheel:(NSEvent*)event;
@end

@implementation AetherResponsiveViewportView
@end

@implementation AetherViewportView (AetherPerformance)

+ (void)load {
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        Class cls = AetherViewportView.class;
        swapInstanceMethods(cls, @selector(setPreferredFramesPerSecond:),
                            @selector(aetherPerf_setPreferredFramesPerSecond:));
        swapInstanceMethods(cls, @selector(setScenePath:), @selector(aetherPerf_setScenePath:));
        swapInstanceMethods(cls, @selector(setDynamicMeshPath:),
                            @selector(aetherPerf_setDynamicMeshPath:));
        swapInstanceMethods(cls, @selector(keyDown:), @selector(aetherPerf_keyDown:));
        swapInstanceMethods(cls, @selector(keyUp:), @selector(aetherPerf_keyUp:));
        swapInstanceMethods(cls, @selector(mouseDown:), @selector(aetherPerf_mouseDown:));
        swapInstanceMethods(cls, @selector(mouseDragged:), @selector(aetherPerf_mouseDragged:));
        swapInstanceMethods(cls, @selector(rightMouseDragged:),
                            @selector(aetherPerf_rightMouseDragged:));
        swapInstanceMethods(cls, @selector(scrollWheel:), @selector(aetherPerf_scrollWheel:));
    });
}

- (MTKView*)aetherPerf_metalView {
    for (NSView* child in self.subviews) {
        if ([child isKindOfClass:MTKView.class])
            return (MTKView*)child;
    }
    return nil;
}

- (NSInteger)aetherPerf_configuredFramesPerSecond {
    NSNumber* value = objc_getAssociatedObject(self, &kConfiguredFpsKey);
    return value ? value.integerValue : 60;
}

- (void)aetherPerf_storeConfiguredFramesPerSecond:(NSInteger)value {
    objc_setAssociatedObject(self, &kConfiguredFpsKey, @(value), OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}

- (NSUInteger)aetherPerf_interactionGeneration {
    NSNumber* value = objc_getAssociatedObject(self, &kInteractionGenerationKey);
    return value ? value.unsignedIntegerValue : 0;
}

- (NSUInteger)aetherPerf_advanceInteractionGeneration {
    const NSUInteger generation = [self aetherPerf_interactionGeneration] + 1;
    objc_setAssociatedObject(self, &kInteractionGenerationKey, @(generation),
                             OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    return generation;
}

- (BOOL)aetherPerf_isInteracting {
    NSNumber* value = objc_getAssociatedObject(self, &kInteractingKey);
    return value.boolValue;
}

- (void)aetherPerf_setInteracting:(BOOL)value {
    objc_setAssociatedObject(self, &kInteractingKey, @(value), OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}

- (BOOL)aetherPerf_isGaussianScene {
    NSString* extension = self.scenePath.pathExtension.lowercaseString;
    return [extension isEqualToString:@"ply"] || [extension isEqualToString:@"aether"];
}

- (CGFloat)aetherPerf_interactiveScale {
    // During navigation we care about latency, not final-pixel fidelity. 0.35x is only ~12% of
    // full drawable pixels and is paired with an 80k Gaussian projection/sort budget.
    return [self aetherPerf_isGaussianScene] ? 0.35 : 0.62;
}

- (void)aetherPerf_applyDrawableScale:(CGFloat)scale {
    MTKView* metalView = [self aetherPerf_metalView];
    if (!metalView)
        return;

    const CGFloat clampedScale = std::clamp(scale, 0.28, 1.0);
    const NSSize backing = [self convertSizeToBacking:self.bounds.size];
    if (backing.width <= 0.0 || backing.height <= 0.0)
        return;

    metalView.autoResizeDrawable = clampedScale >= 0.999;
    const CGFloat width = std::max<CGFloat>(1.0, std::floor(backing.width * clampedScale));
    const CGFloat height = std::max<CGFloat>(1.0, std::floor(backing.height * clampedScale));
    const CGSize current = metalView.drawableSize;
    if (std::abs(current.width - width) > 1.0 || std::abs(current.height - height) > 1.0)
        metalView.drawableSize = CGSizeMake(width, height);
}

- (void)aetherPerf_beginInteraction {
    [self aetherPerf_advanceInteractionGeneration];
    [self aetherPerf_setInteracting:YES];
    if ([self aetherPerf_isGaussianScene])
        aether::metal::setResponsiveGaussianViewportBudget(kInteractiveGaussianBudget);
    [self aetherPerf_applyDrawableScale:[self aetherPerf_interactiveScale]];
    const NSInteger configured = [self aetherPerf_configuredFramesPerSecond];
    [self aetherPerf_setPreferredFramesPerSecond:
              std::max<NSInteger>(configured, kInteractionFpsFloor)];
}

- (void)aetherPerf_restoreFullQuality {
    [self aetherPerf_advanceInteractionGeneration];
    [self aetherPerf_setInteracting:NO];
    aether::metal::setResponsiveGaussianViewportBudget(kSettledGaussianBudget);
    [self aetherPerf_applyDrawableScale:1.0];
    [self aetherPerf_setPreferredFramesPerSecond:[self aetherPerf_configuredFramesPerSecond]];
}

- (void)aetherPerf_finishInteractionIfGenerationMatches:(NSUInteger)generation {
    if ([self aetherPerf_interactionGeneration] != generation)
        return;
    [self aetherPerf_setInteracting:NO];
    aether::metal::setResponsiveGaussianViewportBudget(kSettledGaussianBudget);
    [self aetherPerf_applyDrawableScale:1.0];
    [self aetherPerf_setPreferredFramesPerSecond:[self aetherPerf_configuredFramesPerSecond]];
}

- (void)aetherPerf_scheduleRestore:(NSTimeInterval)delay {
    const NSUInteger generation = [self aetherPerf_interactionGeneration];
    __weak AetherViewportView* weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
                       AetherViewportView* strongSelf = weakSelf;
                       if (strongSelf)
                           [strongSelf aetherPerf_finishInteractionIfGenerationMatches:generation];
                   });
}

- (void)aetherPerf_setPreferredFramesPerSecond:(NSInteger)value {
    const NSInteger configured = std::clamp<NSInteger>(value, 1, 120);
    [self aetherPerf_storeConfiguredFramesPerSecond:configured];
    const NSInteger effective =
        [self aetherPerf_isInteracting]
            ? std::max<NSInteger>(configured, kInteractionFpsFloor)
            : configured;
    // Swizzling makes this selector point at the original implementation.
    [self aetherPerf_setPreferredFramesPerSecond:effective];
}

- (void)aetherPerf_setScenePath:(NSString*)scenePath {
    MTKView* metalView = [self aetherPerf_metalView];
    const BOOL wasPaused = metalView.paused;
    metalView.paused = YES;
    [self aetherPerf_restoreFullQuality];
    [self aetherPerf_setScenePath:scenePath];
    metalView.paused = wasPaused;
}

- (void)aetherPerf_setDynamicMeshPath:(NSString*)dynamicMeshPath {
    MTKView* metalView = [self aetherPerf_metalView];
    const BOOL wasPaused = metalView.paused;
    metalView.paused = YES;
    [self aetherPerf_setDynamicMeshPath:dynamicMeshPath];
    metalView.paused = wasPaused;
}

- (void)aetherPerf_keyDown:(NSEvent*)event {
    NSString* characters = event.charactersIgnoringModifiers.lowercaseString;
    if (characters.length > 0) {
        const unichar key = [characters characterAtIndex:0];
        if (key == 'w' || key == 'a' || key == 's' || key == 'd' || key == 'q' || key == 'e')
            [self aetherPerf_beginInteraction];
    }
    [self aetherPerf_keyDown:event];
}

- (void)aetherPerf_keyUp:(NSEvent*)event {
    [self aetherPerf_keyUp:event];
    [self aetherPerf_scheduleRestore:0.14];
}

- (void)aetherPerf_mouseDown:(NSEvent*)event {
    // The existing picker assumes full drawable-space coordinates.
    [self aetherPerf_restoreFullQuality];
    [self aetherPerf_mouseDown:event];
}

- (void)aetherPerf_mouseDragged:(NSEvent*)event {
    [self aetherPerf_beginInteraction];
    [self aetherPerf_mouseDragged:event];
    [self aetherPerf_scheduleRestore:0.18];
}

- (void)aetherPerf_rightMouseDragged:(NSEvent*)event {
    [self aetherPerf_beginInteraction];
    [self aetherPerf_rightMouseDragged:event];
    [self aetherPerf_scheduleRestore:0.18];
}

- (void)aetherPerf_scrollWheel:(NSEvent*)event {
    [self aetherPerf_beginInteraction];
    [self aetherPerf_scrollWheel:event];
    [self aetherPerf_scheduleRestore:0.20];
}

@end
