#import "AetherPersistentGaussianBridge.h"

BOOL AetherPersistentLoadWorld(AetherPersistentGaussianView* view, NSURL* archiveURL,
                               NSError** error) {
    return [view loadWorldArchiveAtURL:archiveURL error:error];
}

BOOL AetherPersistentLoadGaussianPLY(AetherPersistentGaussianView* view, NSURL* plyURL,
                                     NSError** error) {
    return [view loadGaussianPLYAtURL:plyURL error:error];
}

BOOL AetherPersistentSaveState(AetherPersistentGaussianView* view, NSError** error) {
    return [view savePersistentStateWithError:error];
}

NSData* AetherPersistentEntitiesJSON(AetherPersistentGaussianView* view, NSError** error) {
    return [view entitiesJSONWithError:error];
}

NSData* AetherPersistentOwnershipJSON(AetherPersistentGaussianView* view, NSError** error) {
    return [view ownershipJSONWithError:error];
}

NSData* AetherPersistentTranslateEntity(AetherPersistentGaussianView* view, uint64_t entityId,
                                        float x, float y, float z,
                                        uint64_t timestampNanoseconds, NSError** error) {
    return [view translateEntity:entityId
                               x:x
                               y:y
                               z:z
            timestampNanoseconds:timestampNanoseconds
                           error:error];
}
