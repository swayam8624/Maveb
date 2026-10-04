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
    result.worldBounds = {{-0.4F, -0.4F, 2.6F}, {0.4F, 0.4F, 3.4F}};
    result.representation = aether::world::RepresentationKind::gaussian;
    result.geometrySignature = 1;
    result.appearanceSignature = 1;
    result.confidence = 1.0F;
    return result;
}

aether::gaussian::Gaussian gaussian(float x) {
    aether::gaussian::Gaussian result;
    result.position = {x, 0.0F, 3.0F};
    result.logScale = {-2.0F, -2.0F, -2.0F};
    result.rotation = {1.0F, 0.0F, 0.0F, 0.0F};
    result.opacityLogit = 3.0F;
    result.dc = {0.8F, 0.2F, 0.1F};
    return result;
}

bool createFixture(const std::filesystem::path& archive) {
    aether::world::PersistentWorldModel world;
    auto ingested = world.ingest(100, {entity()});
    if (!ingested)
        return false;
    if (!world.save(archive))
        return false;

    aether::gaussian::GaussianAsset asset;
    asset.name = "fixture-gaussians";
    asset.gaussians = {gaussian(-0.1F), gaussian(0.1F)};
    aether::world_gaussian::GaussianEntityOwnership ownership;
    ownership.owners = {aether::world::EntityId{1}, aether::world::EntityId{1}};
    auto encodedGaussians = aether::gaussian::GaussianCodec::encode(asset);
    auto encodedOwnership = aether::world_gaussian::GaussianOwnershipCodec::encode(ownership);
    return encodedGaussians && encodedOwnership &&
           writeBytes(gaussianSidecar(archive, 1), *encodedGaussians) &&
           writeBytes(ownershipSidecar(archive, 1), *encodedOwnership);
}

void runEdit(const std::filesystem::path& tool, const std::filesystem::path& root,
             std::string_view name, std::string_view editArguments, std::string_view expectedKind) {
    const auto caseRoot = root / std::string(name);
    std::filesystem::create_directories(caseRoot);
    const auto archive = caseRoot / "fixture.world";
    const auto output = caseRoot / "evidence";
    expect(createFixture(archive), "multi-edit fixture must be created");
    if (!std::filesystem::is_regular_file(archive))
        return;

    std::ostringstream command;
    command << '"' << tool.string() << '"' << " --archive " << '"' << archive.string() << '"'
            << " --entity 1"
            << " --edit-kind " << editArguments << " --timestamp 200"
            << " --output-dir " << '"' << output.string() << '"'
            << " --width 64 --height 64 --focal-x 70 --focal-y 70"
            << " --center-x 32 --center-y 32 --epsilon 1.0";
    const int exitCode = std::system(command.str().c_str());
    expect(exitCode == 0, "headless typed edit command must succeed");
    if (exitCode != 0)
        return;

    const std::string transaction = readText(output / "translation.json");
    const std::string certificate = readText(output / "certificate.json");
    expect(transaction.find("\"editKind\":\"" + std::string(expectedKind) + "\"") !=
               std::string::npos,
           "transaction evidence must preserve typed edit kind");
    expect(transaction.find("\"editedGaussians\":2") != std::string::npos,
           "typed transaction must report exact edited primitive count");
    expect(transaction.find("\"persisted\":true") != std::string::npos,
           "typed transaction must report durable persistence");
    expect(certificate.find("\"changedGaussians\":2") != std::string::npos,
           "independent image certificate must cover every edited primitive");

    auto reloaded = aether::world::PersistentWorldModel::load(archive);
    expect(reloaded && reloaded->latest() && reloaded->latest()->revision == 2,
           "typed headless edit must commit exactly one persistent revision");
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
                          ("maveb-cbrc-multiedit-test-" + std::to_string(stamp));
        std::filesystem::create_directories(root);

        runEdit(tool, root, "translation", "translation --target 0.2,0,3", "translation");
        runEdit(tool, root, "rotation", "rotation --rotation-axis 0,0,1 --rotation-radians 0.2",
                "rotation");
        runEdit(tool, root, "scale", "uniform-scale --uniform-scale 1.1", "uniform-scale");
        runEdit(tool, root, "opacity", "opacity --opacity-logit-delta 0.4", "opacity");

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
        std::cout << "Headless CBRC multi-edit tool tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
