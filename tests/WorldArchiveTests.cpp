#include <aether/world/WorldModel.hpp>

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <utility>

namespace {

using aether::world::Bounds;
using aether::world::EntityState;
using aether::world::PersistentWorldModel;
using aether::world::RepresentationKind;
using aether::world::WorldArchiveLimits;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

EntityState observation(std::string name, std::string semantic, float x,
                        std::uint64_t geometrySignature, std::uint64_t appearanceSignature) {
    EntityState result;
    result.name = std::move(name);
    result.semanticLabel = std::move(semantic);
    result.transform.translation = {x, 0.0F, 0.0F};
    result.worldBounds = Bounds{{x - 0.25F, -0.25F, -0.25F},
                                {x + 0.25F, 0.25F, 0.25F}};
    result.representation = RepresentationKind::hybrid;
    result.geometrySignature = geometrySignature;
    result.appearanceSignature = appearanceSignature;
    return result;
}

std::filesystem::path testPath(const char* name) {
    return std::filesystem::temp_directory_path() / name;
}

void cleanup(const std::filesystem::path& path) {
    std::error_code error;
    static_cast<void>(std::filesystem::remove(path, error));
    static_cast<void>(std::filesystem::remove(path.string() + ".tmp", error));
}

void testRoundTripPreservesHistoryAndIdentity() {
    const auto path = testPath("maveb-world-roundtrip.json");
    cleanup(path);

    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk \"A\"\nNorth", "desk", 0.0F, 10, 20),
                              observation("Chair", "chair", 1.0F, 30, 40)})
               .has_value(),
           "archive fixture must create initial world revision");
    expect(model.ingest(200, {observation("Desk \"A\"\nNorth", "desk", 0.0F, 10, 21),
                              observation("Chair", "chair", 1.5F, 30, 40),
                              observation("Lamp", "lamp", 3.0F, 50, 60)})
               .has_value(),
           "archive fixture must create second world revision");

    const std::uint64_t nextIdBefore = model.nextEntityId();
    expect(model.save(path).has_value(), "persistent world model must save atomically");

    auto restored = PersistentWorldModel::load(path);
    expect(restored.has_value(), "saved persistent world archive must load");
    if (!restored) {
        cleanup(path);
        return;
    }

    expect(restored->timeline().size() == 2, "round trip must preserve complete temporal history");
    expect(restored->nextEntityId() == nextIdBefore,
           "round trip must preserve persistent identity allocator state");
    const auto* latest = restored->latest();
    expect(latest && latest->revision == 2 && latest->timestamp == 200,
           "round trip must preserve latest revision metadata");
    expect(latest && latest->entities.size() == 3,
           "round trip must preserve every entity in latest revision");
    if (latest) {
        expect(latest->entities.front().name == "Desk \"A\"\nNorth",
               "archive JSON escaping must round-trip entity names exactly");
    }

    const auto historicalDiff = restored->timeline().latestDiff();
    expect(historicalDiff.has_value(), "restored timeline must remain fully diffable");

    const auto continued = restored->ingest(
        300, {observation("Desk \"A\"\nNorth", "desk", 0.0F, 10, 21),
              observation("Chair", "chair", 1.5F, 30, 40),
              observation("Lamp", "lamp", 3.0F, 50, 60),
              observation("Plant", "plant", 5.0F, 70, 80)});
    expect(continued.has_value(), "restored world must accept future observations normally");
    if (continued) {
        expect(continued->revision == 3, "restored world must continue revision numbering");
        expect(continued->createdIds == 1,
               "new entity after restore must allocate exactly one persistent identity");
    }

    cleanup(path);
}

void testArchiveResourceLimits() {
    const auto path = testPath("maveb-world-limits.json");
    cleanup(path);

    PersistentWorldModel model;
    expect(model.ingest(100, {observation("Desk", "desk", 0.0F, 1, 1)}).has_value(),
           "limit fixture must create first revision");
    expect(model.ingest(200, {observation("Desk", "desk", 0.1F, 1, 1)}).has_value(),
           "limit fixture must create second revision");
    expect(model.save(path).has_value(), "limit fixture must save world archive");

    WorldArchiveLimits limits;
    limits.maximumSnapshots = 1;
    const auto rejected = PersistentWorldModel::load(path, limits);
    expect(!rejected.has_value(), "archive loader must enforce configured snapshot resource limit");
    cleanup(path);
}

void testUnsupportedSchemaIsRejected() {
    const auto path = testPath("maveb-world-schema.json");
    cleanup(path);
    {
        std::ofstream stream(path, std::ios::trunc);
        stream << "{\"schemaVersion\":999,\"nextEntityId\":1,\"snapshots\":[]}\n";
    }
    const auto rejected = PersistentWorldModel::load(path);
    expect(!rejected.has_value(), "unsupported world archive schema must fail closed");
    cleanup(path);
}

} // namespace

int main() noexcept {
    try {
        testRoundTripPreservesHistoryAndIdentity();
        testArchiveResourceLimits();
        testUnsupportedSchemaIsRejected();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Persistent world archive tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
