#import "AetherWorldBridge.h"

#include <aether/canonical/CanonicalAsset.hpp>
#include <aether/world/WorldModel.hpp>
#include <aether/world_adapters/CanonicalObservationAdapter.hpp>

#include <algorithm>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <utility>

namespace {
using aether::world::ChangeFlag;
using aether::world::PersistentWorldModel;
using aether::world::WorldDiff;
using aether::world::WorldSnapshot;

constexpr std::size_t maximumDiffEntitiesForStudio = 5000;

PersistentWorldModel& model(void* storage) {
    return *static_cast<PersistentWorldModel*>(storage);
}

NSString* text(const std::string& value) {
    return [[NSString alloc] initWithBytes:value.data()
                                   length:value.size()
                                 encoding:NSUTF8StringEncoding] ?: @"";
}

void setError(NSError** output, const aether::Error& source) {
    if (!output)
        return;
    NSString* description = text(source.describe());
    *output = [NSError errorWithDomain:@"com.swayamsingal.aether.world"
                                  code:static_cast<NSInteger>(source.code)
                              userInfo:@{NSLocalizedDescriptionKey : description}];
}

NSData* jsonData(id object, NSError** error) {
    return [NSJSONSerialization dataWithJSONObject:object options:0 error:error];
}

NSArray<NSString*>* flagNames(ChangeFlag flags) {
    NSMutableArray<NSString*>* names = [NSMutableArray array];
    const auto add = [&](ChangeFlag flag, NSString* label) {
        if (aether::world::hasFlag(flags, flag))
            [names addObject:label];
    };
    add(ChangeFlag::added, @"added");
    add(ChangeFlag::removed, @"removed");
    add(ChangeFlag::translated, @"translated");
    add(ChangeFlag::rotated, @"rotated");
    add(ChangeFlag::scaled, @"scaled");
    add(ChangeFlag::geometry, @"geometry");
    add(ChangeFlag::appearance, @"appearance");
    add(ChangeFlag::semantic, @"semantic");
    add(ChangeFlag::confidence, @"confidence");
    add(ChangeFlag::representation, @"representation");
    add(ChangeFlag::bounds, @"bounds");
    add(ChangeFlag::metadata, @"metadata");
    return names;
}

NSDictionary* diffSummary(const WorldDiff& diff) {
    return @{
        @"added" : @(diff.summary.added),
        @"removed" : @(diff.summary.removed),
        @"modified" : @(diff.summary.modified),
        @"unchanged" : @(diff.summary.unchanged),
        @"changeRatio" : @(diff.summary.changeRatio),
    };
}

std::unordered_map<std::uint64_t, std::string> entityNames(const WorldSnapshot& before,
                                                           const WorldSnapshot& after) {
    std::unordered_map<std::uint64_t, std::string> names;
    names.reserve(before.entities.size() + after.entities.size());
    for (const auto& entity : before.entities)
        names.emplace(entity.id.value, entity.name);
    for (const auto& entity : after.entities)
        names[entity.id.value] = entity.name;
    return names;
}

NSDictionary* diffPayload(const PersistentWorldModel& world) {
    if (world.timeline().size() < 2) {
        return @{
            @"schemaVersion" : @1,
            @"available" : @NO,
        };
    }

    auto diff = world.timeline().latestDiff();
    if (!diff) {
        return @{
            @"schemaVersion" : @1,
            @"available" : @NO,
            @"error" : text(diff.error().describe()),
        };
    }
    auto before = world.timeline().snapshot(diff->beforeRevision);
    auto after = world.timeline().snapshot(diff->afterRevision);
    if (!before || !after) {
        return @{
            @"schemaVersion" : @1,
            @"available" : @NO,
            @"error" : @"Reality Diff references unavailable world revisions.",
        };
    }
    const auto names = entityNames(**before, **after);
    const std::size_t count = std::min(diff->entities.size(), maximumDiffEntitiesForStudio);
    NSMutableArray* entities = [NSMutableArray arrayWithCapacity:count];
    for (std::size_t index = 0; index < count; ++index) {
        const auto& delta = diff->entities[index];
        const auto name = names.find(delta.id.value);
        [entities addObject:@{
            @"id" : @(delta.id.value),
            @"name" : name == names.end() ? @"" : text(name->second),
            @"flags" : flagNames(delta.flags),
            @"translationMeters" : @(delta.translationMeters),
            @"rotationRadians" : @(delta.rotationRadians),
            @"relativeScale" : @(delta.relativeScale),
            @"boundsMeters" : @(delta.boundsMeters),
            @"confidenceDelta" : @(delta.confidenceDelta),
        }];
    }

    return @{
        @"schemaVersion" : @1,
        @"available" : @YES,
        @"beforeRevision" : @(diff->beforeRevision),
        @"afterRevision" : @(diff->afterRevision),
        @"beforeTimestamp" : @(diff->beforeTimestamp),
        @"afterTimestamp" : @(diff->afterTimestamp),
        @"summary" : diffSummary(*diff),
        @"entities" : entities,
        @"truncated" : @(diff->entities.size() > count),
        @"totalEntityDeltas" : @(diff->entities.size()),
    };
}

} // namespace

@implementation AetherWorldBridge

- (instancetype)init {
    self = [super init];
    if (self)
        _worldModel = new PersistentWorldModel();
    return self;
}

- (void)dealloc {
    delete static_cast<PersistentWorldModel*>(_worldModel);
    _worldModel = nullptr;
}

- (BOOL)loadArchiveAtURL:(NSURL*)archiveURL error:(NSError**)error {
    auto loaded = PersistentWorldModel::load(archiveURL.fileSystemRepresentation);
    if (!loaded) {
        setError(error, loaded.error());
        return NO;
    }
    model(_worldModel) = std::move(*loaded);
    return YES;
}

- (BOOL)saveArchiveAtURL:(NSURL*)archiveURL error:(NSError**)error {
    auto result = model(_worldModel).save(archiveURL.fileSystemRepresentation);
    if (!result) {
        setError(error, result.error());
        return NO;
    }
    return YES;
}

- (NSData*)ingestCanonicalDirectory:(NSURL*)directoryURL
               timestampNanoseconds:(uint64_t)timestampNanoseconds
                              error:(NSError**)error {
    auto canonical = aether::canonical::CanonicalAssetLoader::load(directoryURL.fileSystemRepresentation);
    if (!canonical) {
        setError(error, canonical.error());
        return nil;
    }
    auto observations = aether::world_adapters::observationsFromCanonicalAsset(
        *canonical, timestampNanoseconds);
    if (!observations) {
        setError(error, observations.error());
        return nil;
    }
    auto ingested = model(_worldModel).ingest(timestampNanoseconds, std::move(*observations));
    if (!ingested) {
        setError(error, ingested.error());
        return nil;
    }

    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"revision" : @(ingested->revision),
        @"reusedIds" : @(ingested->reusedIds),
        @"createdIds" : @(ingested->createdIds),
        @"missingPreviousEntities" : @(ingested->missingPreviousEntities),
        @"dirtyRegionCount" : @(ingested->selectiveUpdate.dirtyRegions.size()),
        @"summary" : diffSummary(ingested->diff),
        @"historyCount" : @(model(_worldModel).timeline().size()),
    };
    return jsonData(payload, error);
}

- (NSData*)historyJSONWithError:(NSError**)error {
    const auto& timeline = model(_worldModel).timeline();
    NSMutableArray* snapshots = [NSMutableArray arrayWithCapacity:timeline.size()];
    for (const WorldSnapshot& snapshot : timeline.snapshots()) {
        [snapshots addObject:@{
            @"revision" : @(snapshot.revision),
            @"timestamp" : @(snapshot.timestamp),
            @"entityCount" : @(snapshot.entities.size()),
        }];
    }
    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"snapshots" : snapshots,
        @"nextEntityId" : @(model(_worldModel).nextEntityId()),
    };
    return jsonData(payload, error);
}

- (NSData*)latestDiffJSONWithError:(NSError**)error {
    return jsonData(diffPayload(model(_worldModel)), error);
}

@end

BOOL AetherWorldLoadArchive(AetherWorldBridge* bridge, NSURL* archiveURL, NSError** error) {
    return [bridge loadArchiveAtURL:archiveURL error:error];
}

BOOL AetherWorldSaveArchive(AetherWorldBridge* bridge, NSURL* archiveURL, NSError** error) {
    return [bridge saveArchiveAtURL:archiveURL error:error];
}

NSData* AetherWorldIngestCanonical(AetherWorldBridge* bridge, NSURL* directoryURL,
                                   uint64_t timestampNanoseconds, NSError** error) {
    return [bridge ingestCanonicalDirectory:directoryURL
                       timestampNanoseconds:timestampNanoseconds
                                      error:error];
}

NSData* AetherWorldHistoryJSON(AetherWorldBridge* bridge, NSError** error) {
    return [bridge historyJSONWithError:error];
}

NSData* AetherWorldLatestDiffJSON(AetherWorldBridge* bridge, NSError** error) {
    return [bridge latestDiffJSONWithError:error];
}
