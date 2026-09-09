#import "AetherWorldBridge.h"

#include <aether/canonical/CanonicalAsset.hpp>
#include <aether/world/SpatialSemantics.hpp>
#include <aether/world/WorldModel.hpp>
#include <aether/world_adapters/CanonicalObservationAdapter.hpp>

#include <algorithm>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <utility>

namespace {
using aether::world::ChangeFlag;
using aether::world::EntityId;
using aether::world::EntityPatch;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world::SemanticSpatialIndex;
using aether::world::SpatialQueryPolicy;
using aether::world::WorldDiff;
using aether::world::WorldEditResult;
using aether::world::WorldRevertResult;
using aether::world::WorldSnapshot;

constexpr std::size_t maximumDiffEntitiesForStudio = 5000;
constexpr std::size_t maximumWorldEntitiesForStudio = 5000;
constexpr std::size_t maximumSpatialQueryResultsForStudio = 5000;

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

void setError(NSError** output, aether::ErrorCode code, std::string message,
              std::string context = {}) {
    setError(output, aether::Error{code, std::move(message), std::move(context)});
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

NSString* representationName(RepresentationKind kind) {
    switch (kind) {
    case RepresentationKind::mesh:
        return @"mesh";
    case RepresentationKind::gaussian:
        return @"gaussian";
    case RepresentationKind::hybrid:
        return @"hybrid";
    case RepresentationKind::volumetric:
        return @"volumetric";
    case RepresentationKind::unknown:
        return @"unknown";
    }
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

NSDictionary* editPayload(const WorldEditResult& edit) {
    return @{
        @"schemaVersion" : @1,
        @"revision" : @(edit.candidate.revision),
        @"updatedEntities" : @(edit.updatedEntities),
        @"removedEntities" : @(edit.removedEntities),
        @"dirtyRegionCount" : @(edit.selectiveUpdate.dirtyRegions.size()),
        @"summary" : diffSummary(edit.diff),
    };
}

NSDictionary* revertPayload(const WorldRevertResult& reverted) {
    return @{
        @"schemaVersion" : @1,
        @"revision" : @(reverted.revision),
        @"sourceRevision" : @(reverted.sourceRevision),
        @"dirtyRegionCount" : @(reverted.selectiveUpdate.dirtyRegions.size()),
        @"summary" : diffSummary(reverted.diff),
    };
}

NSDictionary* entityPayload(const EntityState& entity) {
    const simd_float4 rotation = entity.transform.rotation.vector;
    return @{
        @"id" : @(entity.id.value),
        @"name" : text(entity.name),
        @"semanticLabel" : text(entity.semanticLabel),
        @"representation" : representationName(entity.representation),
        @"confidence" : @(entity.confidence),
        @"lastObserved" : @(entity.lastObserved),
        @"geometrySignature" : @(entity.geometrySignature),
        @"appearanceSignature" : @(entity.appearanceSignature),
        @"translation" : @[
            @(entity.transform.translation.x), @(entity.transform.translation.y),
            @(entity.transform.translation.z)
        ],
        @"rotation" : @[@(rotation.x), @(rotation.y), @(rotation.z), @(rotation.w)],
        @"scale" : @[
            @(entity.transform.scale.x), @(entity.transform.scale.y), @(entity.transform.scale.z)
        ],
        @"boundsMinimum" : @[
            @(entity.worldBounds.minimum.x), @(entity.worldBounds.minimum.y),
            @(entity.worldBounds.minimum.z)
        ],
        @"boundsMaximum" : @[
            @(entity.worldBounds.maximum.x), @(entity.worldBounds.maximum.y),
            @(entity.worldBounds.maximum.z)
        ],
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

const EntityState* findEntity(const PersistentWorldModel& world, std::uint64_t entityId) {
    const WorldSnapshot* latest = world.latest();
    if (!latest)
        return nullptr;
    const auto match = std::find_if(latest->entities.begin(), latest->entities.end(),
                                    [entityId](const EntityState& entity) {
                                        return entity.id.value == entityId;
                                    });
    return match == latest->entities.end() ? nullptr : &*match;
}

NSDictionary* compactEntityPayload(const PersistentWorldModel& world, EntityId id) {
    const EntityState* entity = findEntity(world, id.value);
    if (!entity) {
        return @{
            @"id" : @(id.value),
            @"name" : @"",
            @"semanticLabel" : @"",
        };
    }
    return @{
        @"id" : @(entity->id.value),
        @"name" : text(entity->name),
        @"semanticLabel" : text(entity->semanticLabel),
    };
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

Result<SemanticSpatialIndex> spatialIndex(const PersistentWorldModel& world) {
    const WorldSnapshot* latest = world.latest();
    if (!latest)
        return aether::fail(aether::ErrorCode::notFound,
                            "Spatial query requires a committed world revision");
    return SemanticSpatialIndex::build(*latest);
}

Result<std::string> utf8(NSString* value, const char* field) {
    const char* bytes = value.UTF8String;
    if (!bytes)
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Studio string could not be represented as UTF-8", field);
    return std::string(bytes);
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
    auto canonical =
        aether::canonical::CanonicalAssetLoader::load(directoryURL.fileSystemRepresentation);
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

- (NSData*)latestEntitiesJSONWithError:(NSError**)error {
    const WorldSnapshot* latest = model(_worldModel).latest();
    if (!latest) {
        NSDictionary* payload = @{
            @"schemaVersion" : @1,
            @"available" : @NO,
            @"entities" : @[],
        };
        return jsonData(payload, error);
    }

    const std::size_t count = std::min(latest->entities.size(), maximumWorldEntitiesForStudio);
    NSMutableArray* entities = [NSMutableArray arrayWithCapacity:count];
    for (std::size_t index = 0; index < count; ++index)
        [entities addObject:entityPayload(latest->entities[index])];

    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"available" : @YES,
        @"revision" : @(latest->revision),
        @"timestamp" : @(latest->timestamp),
        @"entities" : entities,
        @"truncated" : @(latest->entities.size() > count),
        @"totalEntities" : @(latest->entities.size()),
    };
    return jsonData(payload, error);
}

- (NSData*)translateEntity:(uint64_t)entityId
                         x:(float)x
                         y:(float)y
                         z:(float)z
      timestampNanoseconds:(uint64_t)timestampNanoseconds
                     error:(NSError**)error {
    const EntityState* entity = findEntity(model(_worldModel), entityId);
    if (!entity) {
        setError(error, aether::ErrorCode::notFound, "Persistent world entity was not found",
                 std::to_string(entityId));
        return nil;
    }

    EntityPatch patch;
    patch.id = entity->id;
    patch.transform = entity->transform;
    patch.transform->translation = {x, y, z};
    auto edited = model(_worldModel).edit(timestampNanoseconds, {patch});
    if (!edited) {
        setError(error, edited.error());
        return nil;
    }
    return jsonData(editPayload(*edited), error);
}

- (NSData*)relabelEntity:(uint64_t)entityId
           semanticLabel:(NSString*)semanticLabel
    timestampNanoseconds:(uint64_t)timestampNanoseconds
                   error:(NSError**)error {
    const EntityState* entity = findEntity(model(_worldModel), entityId);
    if (!entity) {
        setError(error, aether::ErrorCode::notFound, "Persistent world entity was not found",
                 std::to_string(entityId));
        return nil;
    }
    auto label = utf8(semanticLabel, "semanticLabel");
    if (!label) {
        setError(error, label.error());
        return nil;
    }

    EntityPatch patch;
    patch.id = entity->id;
    patch.semanticLabel = std::move(*label);
    auto edited = model(_worldModel).edit(timestampNanoseconds, {patch});
    if (!edited) {
        setError(error, edited.error());
        return nil;
    }
    return jsonData(editPayload(*edited), error);
}

- (NSData*)removeEntity:(uint64_t)entityId
   timestampNanoseconds:(uint64_t)timestampNanoseconds
                  error:(NSError**)error {
    const EntityState* entity = findEntity(model(_worldModel), entityId);
    if (!entity) {
        setError(error, aether::ErrorCode::notFound, "Persistent world entity was not found",
                 std::to_string(entityId));
        return nil;
    }

    EntityPatch patch;
    patch.id = entity->id;
    patch.remove = true;
    auto edited = model(_worldModel).edit(timestampNanoseconds, {patch});
    if (!edited) {
        setError(error, edited.error());
        return nil;
    }
    return jsonData(editPayload(*edited), error);
}

- (NSData*)revertToRevision:(uint64_t)sourceRevision
       timestampNanoseconds:(uint64_t)timestampNanoseconds
                      error:(NSError**)error {
    auto reverted = model(_worldModel).revertTo(sourceRevision, timestampNanoseconds);
    if (!reverted) {
        setError(error, reverted.error());
        return nil;
    }
    return jsonData(revertPayload(*reverted), error);
}

- (NSData*)semanticEntities:(NSString*)semanticLabel
                 maxResults:(NSUInteger)maxResults
                      error:(NSError**)error {
    auto label = utf8(semanticLabel, "semanticLabel");
    if (!label) {
        setError(error, label.error());
        return nil;
    }
    auto index = spatialIndex(model(_worldModel));
    if (!index) {
        setError(error, index.error());
        return nil;
    }
    const std::size_t boundedResults =
        std::min<std::size_t>(maxResults, maximumSpatialQueryResultsForStudio);
    auto ids = index->findSemantic(*label, boundedResults);
    if (!ids) {
        setError(error, ids.error());
        return nil;
    }

    NSMutableArray* entities = [NSMutableArray arrayWithCapacity:ids->size()];
    for (const EntityId id : *ids)
        [entities addObject:compactEntityPayload(model(_worldModel), id)];
    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"revision" : @(index->revision()),
        @"semanticLabel" : semanticLabel,
        @"entities" : entities,
    };
    return jsonData(payload, error);
}

- (NSData*)nearestEntitiesFromX:(float)x
                              y:(float)y
                              z:(float)z
                  semanticLabel:(NSString*)semanticLabel
         maximumDistanceMeters:(float)maximumDistanceMeters
                     maxResults:(NSUInteger)maxResults
                          error:(NSError**)error {
    auto label = utf8(semanticLabel, "semanticLabel");
    if (!label) {
        setError(error, label.error());
        return nil;
    }
    auto index = spatialIndex(model(_worldModel));
    if (!index) {
        setError(error, index.error());
        return nil;
    }

    SpatialQueryPolicy policy;
    policy.maximumDistanceMeters = maximumDistanceMeters;
    policy.maximumResults =
        std::min<std::size_t>(maxResults, maximumSpatialQueryResultsForStudio);
    auto hits = index->nearest(simd_float3{x, y, z}, *label, policy);
    if (!hits) {
        setError(error, hits.error());
        return nil;
    }

    NSMutableArray* results = [NSMutableArray arrayWithCapacity:hits->size()];
    for (const auto& hit : *hits) {
        const NSDictionary* entity = compactEntityPayload(model(_worldModel), hit.id);
        [results addObject:@{
            @"id" : entity[@"id"],
            @"name" : entity[@"name"],
            @"semanticLabel" : entity[@"semanticLabel"],
            @"pointToBoundsMeters" : @(hit.pointToBoundsMeters),
            @"centerDistanceMeters" : @(hit.centerDistanceMeters),
        }];
    }
    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"revision" : @(index->revision()),
        @"queryPoint" : @[@(x), @(y), @(z)],
        @"semanticLabel" : semanticLabel,
        @"results" : results,
    };
    return jsonData(payload, error);
}

- (NSData*)relationsFromEntity:(uint64_t)subjectId
                      toEntity:(uint64_t)referenceId
            nearDistanceMeters:(float)nearDistanceMeters
                         error:(NSError**)error {
    auto index = spatialIndex(model(_worldModel));
    if (!index) {
        setError(error, index.error());
        return nil;
    }
    auto relation = index->relations(EntityId{subjectId}, EntityId{referenceId}, nearDistanceMeters);
    if (!relation) {
        setError(error, relation.error());
        return nil;
    }

    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"revision" : @(index->revision()),
        @"subject" : compactEntityPayload(model(_worldModel), relation->subject),
        @"reference" : compactEntityPayload(model(_worldModel), relation->reference),
        @"centerDistanceMeters" : @(relation->centerDistanceMeters),
        @"boundsSeparationMeters" : @(relation->boundsSeparationMeters),
        @"intersects" : @(relation->intersects),
        @"subjectContainsReference" : @(relation->subjectContainsReference),
        @"subjectInsideReference" : @(relation->subjectInsideReference),
        @"near" : @(relation->near),
    };
    return jsonData(payload, error);
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

NSData* AetherWorldLatestEntitiesJSON(AetherWorldBridge* bridge, NSError** error) {
    return [bridge latestEntitiesJSONWithError:error];
}

NSData* AetherWorldTranslateEntity(AetherWorldBridge* bridge, uint64_t entityId, float x, float y,
                                   float z, uint64_t timestampNanoseconds, NSError** error) {
    return [bridge translateEntity:entityId
                                 x:x
                                 y:y
                                 z:z
              timestampNanoseconds:timestampNanoseconds
                             error:error];
}

NSData* AetherWorldRelabelEntity(AetherWorldBridge* bridge, uint64_t entityId,
                                 NSString* semanticLabel, uint64_t timestampNanoseconds,
                                 NSError** error) {
    return [bridge relabelEntity:entityId
                   semanticLabel:semanticLabel
            timestampNanoseconds:timestampNanoseconds
                           error:error];
}

NSData* AetherWorldRemoveEntity(AetherWorldBridge* bridge, uint64_t entityId,
                                uint64_t timestampNanoseconds, NSError** error) {
    return [bridge removeEntity:entityId timestampNanoseconds:timestampNanoseconds error:error];
}

NSData* AetherWorldRevertToRevision(AetherWorldBridge* bridge, uint64_t sourceRevision,
                                    uint64_t timestampNanoseconds, NSError** error) {
    return [bridge revertToRevision:sourceRevision
               timestampNanoseconds:timestampNanoseconds
                              error:error];
}

NSData* AetherWorldSemanticEntities(AetherWorldBridge* bridge, NSString* semanticLabel,
                                    NSUInteger maxResults, NSError** error) {
    return [bridge semanticEntities:semanticLabel maxResults:maxResults error:error];
}

NSData* AetherWorldNearestEntities(AetherWorldBridge* bridge, float x, float y, float z,
                                   NSString* semanticLabel, float maximumDistanceMeters,
                                   NSUInteger maxResults, NSError** error) {
    return [bridge nearestEntitiesFromX:x
                                     y:y
                                     z:z
                         semanticLabel:semanticLabel
                maximumDistanceMeters:maximumDistanceMeters
                            maxResults:maxResults
                                 error:error];
}

NSData* AetherWorldRelations(AetherWorldBridge* bridge, uint64_t subjectId, uint64_t referenceId,
                             float nearDistanceMeters, NSError** error) {
    return [bridge relationsFromEntity:subjectId
                              toEntity:referenceId
                    nearDistanceMeters:nearDistanceMeters
                                 error:error];
}
