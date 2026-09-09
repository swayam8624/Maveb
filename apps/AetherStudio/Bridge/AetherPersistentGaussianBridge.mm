#import "AetherPersistentGaussianBridge.h"

#import <Metal/Metal.h>
#import <MetalKit/MetalKit.h>

#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/gaussian/PlyLoader.hpp>
#include <aether/metal/Renderer.hpp>
#include <aether/world/WorldModel.hpp>
#include <aether/world_gaussian/GaussianLocalUpdate.hpp>
#include <aether/world_gaussian/GaussianOwnershipAssignment.hpp>
#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <span>
#include <string>
#include <system_error>
#include <vector>

namespace {

using aether::gaussian::GaussianAsset;
using aether::world::EntityId;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world_gaussian::GaussianEntityOwnership;

constexpr std::uintmax_t maximumPersistentGaussianBytes = 8ULL * 1024ULL * 1024ULL * 1024ULL;
constexpr std::size_t maximumPersistentGaussians = 100'000'000;
constexpr std::size_t maximumEntitiesForStudio = 10'000;

NSString* text(const std::string& value) {
    return [[NSString alloc] initWithBytes:value.data()
                                   length:value.size()
                                 encoding:NSUTF8StringEncoding] ?: @"";
}

void setError(NSError** output, const aether::Error& source) {
    if (!output)
        return;
    *output = [NSError errorWithDomain:@"com.swayamsingal.aether.persistent-gaussian"
                                  code:static_cast<NSInteger>(source.code)
                              userInfo:@{NSLocalizedDescriptionKey : text(source.describe())}];
}

void setError(NSError** output, aether::ErrorCode code, std::string message,
              std::string context = {}) {
    setError(output, aether::Error{code, std::move(message), std::move(context)});
}

NSData* jsonData(id object, NSError** error) {
    return [NSJSONSerialization dataWithJSONObject:object options:0 error:error];
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

const EntityState* findEntity(const PersistentWorldModel& world, std::uint64_t entityId) {
    const auto* latest = world.latest();
    if (!latest)
        return nullptr;
    const auto match = std::find_if(latest->entities.begin(), latest->entities.end(),
                                    [entityId](const EntityState& entity) {
                                        return entity.id.value == entityId;
                                    });
    return match == latest->entities.end() ? nullptr : &*match;
}

std::filesystem::path gaussianSidecar(const std::filesystem::path& worldArchive,
                                      std::uint64_t revision) {
    return worldArchive.string() + ".gaussians.r" + std::to_string(revision) + ".bin";
}

std::filesystem::path ownershipSidecar(const std::filesystem::path& worldArchive,
                                       std::uint64_t revision) {
    return worldArchive.string() + ".ownership.r" + std::to_string(revision) + ".bin";
}

aether::Result<std::vector<std::byte>> readBinaryFile(const std::filesystem::path& path,
                                                       std::uintmax_t maximumBytes) {
    std::error_code filesystemError;
    const auto size = std::filesystem::file_size(path, filesystemError);
    if (filesystemError)
        return aether::fail(aether::ErrorCode::notFound, "Persistent sidecar is unavailable", path);
    if (size == 0 || size > maximumBytes || size > std::numeric_limits<std::size_t>::max()) {
        return aether::fail(aether::ErrorCode::resourceExhausted,
                            "Persistent sidecar byte size is invalid", path);
    }
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    std::ifstream stream(path, std::ios::binary);
    stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!stream)
        return aether::fail(aether::ErrorCode::io, "Unable to read persistent sidecar", path);
    return bytes;
}

aether::Result<void> atomicWrite(const std::filesystem::path& path,
                                 std::span<const std::byte> bytes) {
    if (bytes.empty())
        return aether::fail(aether::ErrorCode::invalidArgument,
                            "Persistent sidecar payload cannot be empty", path);
    const std::filesystem::path temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        return aether::fail(aether::ErrorCode::io, "Unable to write persistent sidecar", path);
    }
    std::error_code filesystemError;
    std::filesystem::rename(temporary, path, filesystemError);
    if (filesystemError) {
        std::filesystem::remove(temporary, filesystemError);
        return aether::fail(aether::ErrorCode::io, "Unable to publish persistent sidecar",
                            filesystemError.message());
    }
    return {};
}

aether::Result<GaussianEntityOwnership> assignOwnership(const GaussianAsset& asset,
                                                         const PersistentWorldModel& world) {
    const auto* latest = world.latest();
    if (!latest)
        return aether::fail(aether::ErrorCode::notFound,
                            "Gaussian ownership requires a committed world revision");
    aether::world_gaussian::GaussianOwnershipAssignmentPolicy policy;
    // Canonical mesh observations and Gaussian appearance may represent the same captured object.
    // Until semantic segmentation upgrades those entities to hybrid/gaussian explicitly, bounds are
    // still a valid deterministic ownership source.
    policy.requireGaussianRepresentation = false;
    auto assigned = aether::world_gaussian::assignGaussianOwnership(asset, *latest, policy);
    if (!assigned)
        return std::unexpected(assigned.error());
    return std::move(assigned->ownership);
}

aether::Result<void> persistState(const std::filesystem::path& archivePath,
                                  const PersistentWorldModel& world, const GaussianAsset& asset,
                                  const GaussianEntityOwnership& ownership) {
    const auto* latest = world.latest();
    if (!latest)
        return aether::fail(aether::ErrorCode::notFound,
                            "Persistent Gaussian state requires a committed world revision");
    if (ownership.owners.size() != asset.gaussians.size()) {
        return aether::fail(aether::ErrorCode::corruptData,
                            "Gaussian ownership cardinality does not match the edited field");
    }

    auto gaussianBytes = aether::gaussian::GaussianCodec::encode(asset);
    if (!gaussianBytes)
        return std::unexpected(gaussianBytes.error());
    auto ownershipBytes = aether::world_gaussian::GaussianOwnershipCodec::encode(ownership);
    if (!ownershipBytes)
        return std::unexpected(ownershipBytes.error());

    // Revision-addressed immutable sidecars are published first. The world archive is saved last and
    // therefore acts as the commit marker. A crash before the final save can leave harmless orphan
    // sidecars, while an archive-visible revision always has both complete representation files.
    if (auto saved = atomicWrite(gaussianSidecar(archivePath, latest->revision), *gaussianBytes);
        !saved)
        return saved;
    if (auto saved = atomicWrite(ownershipSidecar(archivePath, latest->revision), *ownershipBytes);
        !saved)
        return saved;
    return world.save(archivePath);
}

NSDictionary* entityPayload(const EntityState& entity) {
    return @{
        @"id" : @(entity.id.value),
        @"name" : text(entity.name),
        @"semanticLabel" : text(entity.semanticLabel),
        @"representation" : representationName(entity.representation),
        @"confidence" : @(entity.confidence),
        @"translation" : @[
            @(entity.transform.translation.x), @(entity.transform.translation.y),
            @(entity.transform.translation.z)
        ],
    };
}

} // namespace

@interface AetherPersistentGaussianDelegate : NSObject <MTKViewDelegate>
@property(nonatomic, readonly, copy) NSString* rendererStatus;
- (instancetype)initWithDevice:(id<MTLDevice>)device;
- (BOOL)loadWorldArchiveAtURL:(NSURL*)archiveURL error:(NSError**)error;
- (BOOL)loadGaussianPLYAtURL:(NSURL*)plyURL error:(NSError**)error;
- (BOOL)savePersistentStateWithError:(NSError**)error;
- (NSData*)entitiesJSONWithError:(NSError**)error;
- (NSData*)ownershipJSONWithError:(NSError**)error;
- (NSData*)translateEntity:(uint64_t)entityId
                         x:(float)x
                         y:(float)y
                         z:(float)z
      timestampNanoseconds:(uint64_t)timestampNanoseconds
                     error:(NSError**)error;
@end

@implementation AetherPersistentGaussianDelegate {
    std::unique_ptr<aether::metal::Renderer> _renderer;
    std::unique_ptr<PersistentWorldModel> _world;
    std::unique_ptr<GaussianAsset> _gaussians;
    std::unique_ptr<GaussianEntityOwnership> _ownership;
    std::filesystem::path _archivePath;
    NSString* _rendererStatus;
}

- (instancetype)initWithDevice:(id<MTLDevice>)device {
    self = [super init];
    if (!self)
        return nil;
    auto renderer =
        aether::metal::Renderer::create(reinterpret_cast<MTL::Device*>((__bridge void*)device));
    if (!renderer) {
        _rendererStatus = text(renderer.error().describe());
        return self;
    }
    _renderer = std::move(*renderer);
    _rendererStatus = text("Live persistent renderer · " + _renderer->capabilities().name);
    return self;
}

- (NSString*)rendererStatus {
    return _rendererStatus ?: @"Persistent renderer unavailable";
}

- (void)drawInMTKView:(MTKView*)view {
    if (_renderer)
        _renderer->draw(reinterpret_cast<MTK::View*>((__bridge void*)view));
}

- (void)mtkView:(MTKView*)view drawableSizeWillChange:(CGSize)size {
    (void)view;
    if (_renderer)
        _renderer->drawableSizeWillChange(size);
}

- (BOOL)loadWorldArchiveAtURL:(NSURL*)archiveURL error:(NSError**)error {
    if (!_renderer || !archiveURL.isFileURL) {
        setError(error, aether::ErrorCode::invalidArgument,
                 "Live persistent world requires a file archive and Metal renderer");
        return NO;
    }
    auto loadedWorld = PersistentWorldModel::load(archiveURL.fileSystemRepresentation);
    if (!loadedWorld) {
        setError(error, loadedWorld.error());
        return NO;
    }

    const std::filesystem::path archivePath = archiveURL.fileSystemRepresentation;
    const auto* latest = loadedWorld->latest();
    std::unique_ptr<GaussianAsset> restoredGaussians;
    std::unique_ptr<GaussianEntityOwnership> restoredOwnership;
    if (latest) {
        const auto gaussianPath = gaussianSidecar(archivePath, latest->revision);
        const auto ownerPath = ownershipSidecar(archivePath, latest->revision);
        std::error_code filesystemError;
        const bool hasGaussians = std::filesystem::is_regular_file(gaussianPath, filesystemError);
        filesystemError.clear();
        const bool hasOwnership = std::filesystem::is_regular_file(ownerPath, filesystemError);
        if (hasGaussians != hasOwnership) {
            setError(error, aether::ErrorCode::corruptData,
                     "Persistent revision has an incomplete Gaussian sidecar pair",
                     std::to_string(latest->revision));
            return NO;
        }
        if (hasGaussians) {
            auto gaussianBytes = readBinaryFile(gaussianPath, maximumPersistentGaussianBytes);
            if (!gaussianBytes) {
                setError(error, gaussianBytes.error());
                return NO;
            }
            auto decoded = aether::gaussian::GaussianCodec::decode(*gaussianBytes,
                                                                   maximumPersistentGaussians);
            if (!decoded) {
                setError(error, decoded.error());
                return NO;
            }
            auto ownerBytes = readBinaryFile(ownerPath, maximumPersistentGaussianBytes);
            if (!ownerBytes) {
                setError(error, ownerBytes.error());
                return NO;
            }
            auto decodedOwnership = aether::world_gaussian::GaussianOwnershipCodec::decode(
                *ownerBytes, maximumPersistentGaussians);
            if (!decodedOwnership) {
                setError(error, decodedOwnership.error());
                return NO;
            }
            if (decodedOwnership->owners.size() != decoded->gaussians.size()) {
                setError(error, aether::ErrorCode::corruptData,
                         "Persistent Gaussian sidecars disagree on primitive count");
                return NO;
            }
            if (auto rendered = _renderer->loadGaussianAsset(*decoded); !rendered) {
                setError(error, rendered.error());
                return NO;
            }
            restoredGaussians = std::make_unique<GaussianAsset>(std::move(*decoded));
            restoredOwnership =
                std::make_unique<GaussianEntityOwnership>(std::move(*decodedOwnership));
        } else {
            _renderer->clearCapturedGaussianScene();
        }
    } else {
        _renderer->clearCapturedGaussianScene();
    }

    _world = std::make_unique<PersistentWorldModel>(std::move(*loadedWorld));
    _gaussians = std::move(restoredGaussians);
    _ownership = std::move(restoredOwnership);
    _archivePath = archivePath;
    return YES;
}

- (BOOL)loadGaussianPLYAtURL:(NSURL*)plyURL error:(NSError**)error {
    if (!_renderer || !_world || _archivePath.empty() || !plyURL.isFileURL) {
        setError(error, aether::ErrorCode::invalidArgument,
                 "Load a persistent world before importing its Gaussian PLY");
        return NO;
    }
    auto loaded = aether::gaussian::PlyLoader::load(plyURL.fileSystemRepresentation);
    if (!loaded) {
        setError(error, loaded.error());
        return NO;
    }
    auto ownership = assignOwnership(*loaded, *_world);
    if (!ownership) {
        setError(error, ownership.error());
        return NO;
    }
    if (auto rendered = _renderer->loadGaussianAsset(*loaded); !rendered) {
        setError(error, rendered.error());
        return NO;
    }

    _gaussians = std::make_unique<GaussianAsset>(std::move(*loaded));
    _ownership = std::make_unique<GaussianEntityOwnership>(std::move(*ownership));
    auto persisted = persistState(_archivePath, *_world, *_gaussians, *_ownership);
    if (!persisted) {
        setError(error, persisted.error());
        return NO;
    }
    return YES;
}

- (BOOL)savePersistentStateWithError:(NSError**)error {
    if (!_world || !_gaussians || !_ownership || _archivePath.empty()) {
        setError(error, aether::ErrorCode::notFound,
                 "Live persistent state is incomplete and cannot be saved");
        return NO;
    }
    auto persisted = persistState(_archivePath, *_world, *_gaussians, *_ownership);
    if (!persisted) {
        setError(error, persisted.error());
        return NO;
    }
    return YES;
}

- (NSData*)entitiesJSONWithError:(NSError**)error {
    if (!_world || !_world->latest()) {
        return jsonData(@{@"schemaVersion" : @1, @"available" : @NO, @"entities" : @[]}, error);
    }
    const auto& latest = *_world->latest();
    const std::size_t count = std::min(latest.entities.size(), maximumEntitiesForStudio);
    NSMutableArray* entities = [NSMutableArray arrayWithCapacity:count];
    for (std::size_t index = 0; index < count; ++index)
        [entities addObject:entityPayload(latest.entities[index])];
    return jsonData(@{
        @"schemaVersion" : @1,
        @"available" : @YES,
        @"revision" : @(latest.revision),
        @"timestamp" : @(latest.timestamp),
        @"entities" : entities,
        @"truncated" : @(latest.entities.size() > count),
        @"totalEntities" : @(latest.entities.size()),
        @"gaussianStateLoaded" : @(_gaussians != nullptr && _ownership != nullptr),
    }, error);
}

- (NSData*)ownershipJSONWithError:(NSError**)error {
    if (!_gaussians || !_ownership) {
        return jsonData(@{@"schemaVersion" : @1, @"available" : @NO}, error);
    }
    std::size_t assigned{};
    for (const EntityId owner : _ownership->owners)
        assigned += owner.valid() ? 1U : 0U;
    const std::size_t unassigned = _ownership->owners.size() - assigned;
    return jsonData(@{
        @"schemaVersion" : @1,
        @"available" : @YES,
        @"gaussianCount" : @(_gaussians->gaussians.size()),
        @"assigned" : @(assigned),
        @"unassigned" : @(unassigned),
        @"coverage" : @(_ownership->owners.empty()
                            ? 0.0
                            : static_cast<double>(assigned) /
                                  static_cast<double>(_ownership->owners.size())),
    }, error);
}

- (NSData*)translateEntity:(uint64_t)entityId
                         x:(float)x
                         y:(float)y
                         z:(float)z
      timestampNanoseconds:(uint64_t)timestampNanoseconds
                     error:(NSError**)error {
    if (!_renderer || !_world || !_gaussians || !_ownership) {
        setError(error, aether::ErrorCode::notFound,
                 "Live persistent translation requires world, Gaussian field, and ownership");
        return nil;
    }
    const EntityState* state = findEntity(*_world, entityId);
    if (!state) {
        setError(error, aether::ErrorCode::notFound, "Persistent entity was not found",
                 std::to_string(entityId));
        return nil;
    }
    const simd_float3 target{x, y, z};
    const simd_float3 delta = target - state->transform.translation;

    std::vector<std::uint32_t> ownedIndices;
    for (std::size_t index = 0; index < _ownership->owners.size(); ++index) {
        if (_ownership->owners[index].value != entityId)
            continue;
        if (index > std::numeric_limits<std::uint32_t>::max()) {
            setError(error, aether::ErrorCode::resourceExhausted,
                     "Owned Gaussian source index exceeds renderer ID range");
            return nil;
        }
        ownedIndices.push_back(static_cast<std::uint32_t>(index));
    }
    if (ownedIndices.empty()) {
        setError(error, aether::ErrorCode::notFound,
                 "Selected persistent entity owns no Gaussian primitives",
                 std::to_string(entityId));
        return nil;
    }

    if (auto preflight = _renderer->validateGaussianTranslation(ownedIndices, delta); !preflight) {
        setError(error, preflight.error());
        return nil;
    }
    auto edited = aether::world_gaussian::translatePersistentGaussianEntity(
        *_world, *_gaussians, *_ownership, EntityId{entityId}, target, timestampNanoseconds);
    if (!edited) {
        setError(error, edited.error());
        return nil;
    }

    auto rendered = _renderer->translateGaussians(ownedIndices, delta);
    if (!rendered) {
        // World + CPU Gaussian state has already committed. Full re-upload from that authoritative
        // CPU state converges the renderer if an unexpected live-subset publication fails.
        auto recovered = _renderer->loadGaussianAsset(*_gaussians);
        if (!recovered) {
            setError(error, aether::ErrorCode::metal,
                     "Persistent edit committed but renderer recovery failed",
                     rendered.error().describe() + " · " + recovered.error().describe());
            return nil;
        }
    }

    const auto persistence = persistState(_archivePath, *_world, *_gaussians, *_ownership);
    NSDictionary* payload = @{
        @"schemaVersion" : @1,
        @"revision" : @(edited->worldEdit.candidate.revision),
        @"translatedGaussians" : @(edited->translatedGaussians),
        @"reoptimizationGaussians" : @(edited->reoptimizationSelection.gaussianIndices.size()),
        @"protectedStableGaussians" :
            @(edited->reoptimizationSelection.rejectedStableOwnedGaussians),
        @"conservativeBoundaryGaussians" :
            @(edited->reoptimizationSelection.conservativeUnownedMatches),
        @"dirtyRegionCount" : @(edited->worldEdit.selectiveUpdate.dirtyRegions.size()),
        @"persisted" : @(persistence.has_value()),
        @"persistenceError" : persistence ? @"" : text(persistence.error().describe()),
    };
    return jsonData(payload, error);
}

@end

@implementation AetherPersistentGaussianView {
    MTKView* _metalView;
    AetherPersistentGaussianDelegate* _rendererDelegate;
}

- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (!self)
        return nil;
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    _metalView = [[MTKView alloc] initWithFrame:self.bounds device:device];
    _metalView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    _metalView.colorPixelFormat = MTLPixelFormatBGRA8Unorm_sRGB;
    _metalView.depthStencilPixelFormat = MTLPixelFormatDepth32Float;
    _metalView.framebufferOnly = NO;
    _metalView.clearDepth = 0.0;
    _metalView.clearColor = MTLClearColorMake(0.012, 0.016, 0.024, 1.0);
    _metalView.preferredFramesPerSecond = 60;
    _metalView.enableSetNeedsDisplay = NO;
    _metalView.paused = NO;
    _rendererDelegate = [[AetherPersistentGaussianDelegate alloc] initWithDevice:device];
    _metalView.delegate = _rendererDelegate;
    [self addSubview:_metalView];
    return self;
}

- (NSString*)rendererStatus {
    return _rendererDelegate.rendererStatus;
}

- (NSInteger)preferredFramesPerSecond {
    return _metalView.preferredFramesPerSecond;
}

- (void)setPreferredFramesPerSecond:(NSInteger)value {
    _metalView.preferredFramesPerSecond = std::clamp<NSInteger>(value, 15, 120);
}

- (BOOL)loadWorldArchiveAtURL:(NSURL*)archiveURL error:(NSError**)error {
    return [_rendererDelegate loadWorldArchiveAtURL:archiveURL error:error];
}

- (BOOL)loadGaussianPLYAtURL:(NSURL*)plyURL error:(NSError**)error {
    return [_rendererDelegate loadGaussianPLYAtURL:plyURL error:error];
}

- (BOOL)savePersistentStateWithError:(NSError**)error {
    return [_rendererDelegate savePersistentStateWithError:error];
}

- (NSData*)entitiesJSONWithError:(NSError**)error {
    return [_rendererDelegate entitiesJSONWithError:error];
}

- (NSData*)ownershipJSONWithError:(NSError**)error {
    return [_rendererDelegate ownershipJSONWithError:error];
}

- (NSData*)translateEntity:(uint64_t)entityId
                         x:(float)x
                         y:(float)y
                         z:(float)z
      timestampNanoseconds:(uint64_t)timestampNanoseconds
                     error:(NSError**)error {
    return [_rendererDelegate translateEntity:entityId
                                            x:x
                                            y:y
                                            z:z
                         timestampNanoseconds:timestampNanoseconds
                                        error:error];
}

@end
