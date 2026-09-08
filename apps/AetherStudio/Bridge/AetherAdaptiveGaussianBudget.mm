#import <AppKit/AppKit.h>

#include <aether/metal/GaussianPipeline.hpp>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>

namespace {
std::atomic<std::uint64_t> gInteractionGeneration{0};
id gAdaptiveGaussianEventMonitor = nil;

bool isNavigationKey(NSEvent* event) {
    NSString* characters = event.charactersIgnoringModifiers.lowercaseString;
    if (characters.length == 0)
        return false;
    const unichar key = [characters characterAtIndex:0];
    return key == 'w' || key == 'a' || key == 's' || key == 'd' || key == 'q' || key == 'e';
}

std::uint32_t dragBudget(NSEvent* event) {
    const double magnitude = std::hypot(event.deltaX, event.deltaY);
    if (magnitude >= 18.0)
        return 35'000;
    if (magnitude >= 8.0)
        return 45'000;
    if (magnitude >= 3.0)
        return 60'000;
    return 72'000;
}

std::uint32_t scrollBudget(NSEvent* event) {
    const double magnitude = std::abs(event.scrollingDeltaY) + 0.35 * std::abs(event.scrollingDeltaX);
    if (magnitude >= 20.0)
        return 40'000;
    if (magnitude >= 8.0)
        return 52'000;
    return 68'000;
}

void setBudgetAfterCurrentEvent(std::uint64_t generation, std::uint32_t budget) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (gInteractionGeneration.load(std::memory_order_relaxed) != generation)
            return;
        aether::metal::setResponsiveGaussianViewportBudget(budget);
    });
}

void scheduleProgressiveRecovery(std::uint64_t generation) {
    struct RecoveryStep {
        double delaySeconds;
        std::uint32_t budget;
    };
    // Spatially progressive ordering means each prefix already covers the whole world. Recover
    // density gradually so the first settled frames do not spike from interaction cost to 240k.
    constexpr RecoveryStep steps[] = {
        {0.20, 105'000},
        {0.48, 145'000},
        {0.82, 190'000},
        {1.25, 240'000},
    };

    for (const RecoveryStep& step : steps) {
        dispatch_after(
            dispatch_time(DISPATCH_TIME_NOW,
                          static_cast<int64_t>(step.delaySeconds * static_cast<double>(NSEC_PER_SEC))),
            dispatch_get_main_queue(), ^{
                if (gInteractionGeneration.load(std::memory_order_relaxed) != generation)
                    return;
                aether::metal::setResponsiveGaussianViewportBudget(step.budget);
            });
    }
}

void noteInteraction(std::uint32_t budget) {
    const std::uint64_t generation =
        gInteractionGeneration.fetch_add(1, std::memory_order_relaxed) + 1;
    // The viewport handler applies its generic budget first. Re-apply the motion-sensitive value on
    // the next main-queue turn so stronger movement gets a substantially cheaper Gaussian workload.
    setBudgetAfterCurrentEvent(generation, budget);
    scheduleProgressiveRecovery(generation);
}
} // namespace

@interface AetherAdaptiveGaussianBudgetInstaller : NSObject
@end

@implementation AetherAdaptiveGaussianBudgetInstaller

+ (void)load {
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        const NSEventMask mask = NSEventMaskKeyDown | NSEventMaskKeyUp |
                                 NSEventMaskLeftMouseDragged | NSEventMaskRightMouseDragged |
                                 NSEventMaskScrollWheel;
        gAdaptiveGaussianEventMonitor =
            [NSEvent addLocalMonitorForEventsMatchingMask:mask
                                                   handler:^NSEvent*(NSEvent* event) {
                                                       switch (event.type) {
                                                       case NSEventTypeKeyDown:
                                                           if (isNavigationKey(event))
                                                               noteInteraction(50'000);
                                                           break;
                                                       case NSEventTypeKeyUp:
                                                           if (isNavigationKey(event)) {
                                                               const std::uint64_t generation =
                                                                   gInteractionGeneration.load(
                                                                       std::memory_order_relaxed);
                                                               scheduleProgressiveRecovery(generation);
                                                           }
                                                           break;
                                                       case NSEventTypeLeftMouseDragged:
                                                       case NSEventTypeRightMouseDragged:
                                                           noteInteraction(dragBudget(event));
                                                           break;
                                                       case NSEventTypeScrollWheel:
                                                           noteInteraction(scrollBudget(event));
                                                           break;
                                                       default:
                                                           break;
                                                       }
                                                       return event;
                                                   }];
    });
}

@end
