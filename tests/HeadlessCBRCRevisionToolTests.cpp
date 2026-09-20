#include <aether/gaussian/GaussianCodec.hpp>
#include <aether/world/WorldModel.hpp>
#include <aether/world_gaussian/GaussianOwnershipCodec.hpp>

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <span>
#include <sstream>
#include <string>
#include <vector>

namespace {

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

bool writeBytes(const std::filesystem::path& path, std::span<const std::byte> bytes) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
    return static_cast<bool>(stream);
}

std::string readText(const std::filesystem::path& path) {
    std::ifstream stream(path);
    std::ostringstream text;
    text << stream.rdbuf();
    return text.str();
}

std::filesystem::path gaussianSidecar(const std::filesystem::path& archive,
                                      std::uint64_t revision) {
    return archive.string() + ".gaussians.r" + std::to_string(revision) + ".bin";
}

std::filesystem::path ownershipSidecar(const std::filesystem::path& archive,
                                       std::uint64_t revision) {
    return archive.string() + ".ownership.r" + std::to_string(revision) + ".bin";
}

aether::world::EntityState entity() {
    aether::world::EntityState result;
    result.name = "fixture-object";
    result.semanticLabel = "fixture";
    result.transform.translation = {0.0F, 0.0F, 3.0F};
    result.worldBounds = {
        {-0.4F, -0.4F, 2.6F},
        {0.4F, 0.4F, 3.4F},
    };
    result.representation = aether::world::RepresentationKind::gaussian;
    result.geometrySignature = 1;
    result.appearanceSignature = 1;
    result.confidence = 1.0F;
    return result;
}

aether::gaussian::Gaussian gaussian(float x) {
    aether::gaussian::Gaussian result;
    result.position = {x, 0.0F, 3.0F};
    const float logScale = -2.0F;
    result.logScale = {logScale, logScale, logScale};
    result.opacityLogit = 3.0F;
    result.dc = {0.8F, 0.2F, 0.1F};
    return result;
}

} // namespace

int main(int argc, char** argv) noexcept {
    try {
        if (argc != 2) {
            std::cerr << "Expected path to maveb-cbrc-revision\n";
            return EXIT_FAILURE;
        }
        const std::filesystem::path tool = argv[1];
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        const auto root = std::filesystem::temp_directory_path() /
                          ("maveb-cbrc-revision-test-" + std::to_string(stamp));
        std::filesystem::create_directories(root);
        const auto archive = root / "fixture.world";
        const auto output = root / "evidence";

        aether::world::PersistentWorldModel world;
        auto ingested = world.ingest(100, {entity()});
        expect(ingested.has_value(), "fixture world must ingest");
        if (!ingested)
            return EXIT_FAILURE;
        expect(world.latest() && world.latest()->revision == 1,
               "fixture world must start at revision 1");
        auto saved = world.save(archive);
        expect(saved.has_value(), "fixture world must save");
        if (!saved)
            return EXIT_FAILURE;

        aether::gaussian::GaussianAsset asset;
        asset.name = "fixture-gaussians";
        asset.gaussians = {
            gaussian(-0.1F),
            gaussian(0.1F),
        };
        aether::world_gaussian::GaussianEntityOwnership ownership;
        ownership.owners = {
            aether::world::EntityId{1},
            aether::world::EntityId{1},
        };

        auto encodedGaussians = aether::gaussian::GaussianCodec::encode(asset);
        auto encodedOwnership = aether::world_gaussian::GaussianOwnershipCodec::encode(ownership);
        expect(encodedGaussians.has_value() && encodedOwnership.has_value(),
               "fixture sidecars must encode");
        if (!encodedGaussians || !encodedOwnership)
            return EXIT_FAILURE;
        expect(writeBytes(gaussianSidecar(archive, 1), *encodedGaussians),
               "fixture Gaussian sidecar must write");
        expect(writeBytes(ownershipSidecar(archive, 1), *encodedOwnership),
               "fixture ownership sidecar must write");

        std::ostringstream command;
        command << '"' << tool.string() << '"' << " --archive " << '"' << archive.string() << '"'
                << " --entity 1"
                << " --target 0.2,0,3"
                << " --timestamp 200"
                << " --output-dir " << '"' << output.string() << '"' << " --width 64 --height 64"
                << " --focal-x 70 --focal-y 70"
                << " --center-x 32 --center-y 32"
                << " --epsilon 1.0";
        const int exitCode = std::system(command.str().c_str());
        expect(exitCode == 0, "headless CBRC revision tool must succeed");

        expect(std::filesystem::is_regular_file(output / "translation.json"),
               "translation evidence JSON must exist");
        expect(std::filesystem::is_regular_file(output / "certificate.json"),
               "certificate evidence JSON must exist");
        expect(std::filesystem::is_regular_file(gaussianSidecar(archive, 2)),
               "new immutable Gaussian revision sidecar must exist");
        expect(std::filesystem::is_regular_file(ownershipSidecar(archive, 2)),
               "new immutable ownership revision sidecar must exist");

        const std::string translation = readText(output / "translation.json");
        const std::string certificate = readText(output / "certificate.json");
        expect(translation.find("\"persisted\":true") != std::string::npos,
               "translation evidence must report durable persistence");
        expect(translation.find("\"usedOverlayIndex\":true") != std::string::npos,
               "translation evidence must use indexed locality path");
        expect(certificate.find("\"available\":true") != std::string::npos,
               "certificate evidence must be available");
        expect(certificate.find("\"outputConePlanner\"") != std::string::npos,
               "certificate evidence must include planner decision");

        auto reloaded = aether::world::PersistentWorldModel::load(archive);
        expect(reloaded.has_value() && reloaded->latest() && reloaded->latest()->revision == 2,
               "headless CBRC tool must commit revision 2");

        std::error_code ignored;
        std::filesystem::remove_all(root, ignored);
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Headless CBRC revision tool test passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
