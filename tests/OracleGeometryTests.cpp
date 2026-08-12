#include <aether/reconstruction/DenseTsdfVolume.hpp>
#include <aether/reconstruction/ReferenceMarchingCubes.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <optional>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using Field = std::function<double(double, double, double)>;

struct Topology final {
    std::size_t vertices{};
    std::size_t triangles{};
    std::size_t boundaryEdges{};
    std::size_t interiorBoundaryEdges{};
    std::size_t nonManifoldEdges{};
    std::size_t connectedComponents{};
    std::int64_t eulerCharacteristic{};
};

struct FixtureResult final {
    std::string name;
    std::string extractor;
    double voxelSizeMetres{};
    double meanSurfaceErrorMetres{};
    double p95SurfaceErrorMetres{};
    double maximumSurfaceErrorMetres{};
    Topology topology;
};

struct AmbiguityResult final {
    Topology production;
    Topology reference;
};

class DisjointSet final {
  public:
    explicit DisjointSet(std::size_t size) : parents_(size), ranks_(size) {
        std::iota(parents_.begin(), parents_.end(), 0);
    }

    std::size_t find(std::size_t value) {
        if (parents_[value] != value)
            parents_[value] = find(parents_[value]);
        return parents_[value];
    }

    void join(std::size_t left, std::size_t right) {
        left = find(left);
        right = find(right);
        if (left == right)
            return;
        if (ranks_[left] < ranks_[right])
            std::swap(left, right);
        parents_[right] = left;
        if (ranks_[left] == ranks_[right])
            ++ranks_[left];
    }

  private:
    std::vector<std::size_t> parents_;
    std::vector<std::uint8_t> ranks_;
};

void require(bool condition, const std::string& message) {
    if (!condition)
        throw std::runtime_error(message);
}

std::size_t gridIndex(const aether::reconstruction::DenseTsdfConfig& config, std::uint32_t x,
                      std::uint32_t y, std::uint32_t z) {
    return (static_cast<std::size_t>(z) * config.dimensions[1] + y) * config.dimensions[0] + x;
}

std::vector<aether::reconstruction::TsdfVoxel>
makeField(const aether::reconstruction::DenseTsdfConfig& config, const Field& field) {
    const auto count = static_cast<std::size_t>(config.dimensions[0]) * config.dimensions[1] *
                       config.dimensions[2];
    std::vector<aether::reconstruction::TsdfVoxel> voxels(count);
    for (std::uint32_t z = 0; z < config.dimensions[2]; ++z) {
        for (std::uint32_t y = 0; y < config.dimensions[1]; ++y) {
            for (std::uint32_t x = 0; x < config.dimensions[0]; ++x) {
                const auto px = config.originMetres[0] + x * config.voxelSizeMetres;
                const auto py = config.originMetres[1] + y * config.voxelSizeMetres;
                const auto pz = config.originMetres[2] + z * config.voxelSizeMetres;
                auto& voxel = voxels[gridIndex(config, x, y, z)];
                voxel.distance = static_cast<float>(
                    std::clamp(field(px, py, pz) / config.truncationDistanceMetres, -1.0, 1.0));
                voxel.weight = 1.0F;
                voxel.color = {0.25F, 0.5F, 0.75F};
                voxel.observations = 1;
            }
        }
    }
    return voxels;
}

bool onVolumeBoundary(const aether::reconstruction::DenseTsdfConfig& config,
                      const simd_float3& point) {
    constexpr double epsilonScale = 1.0e-4;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto minimum = config.originMetres[axis];
        const auto maximum =
            minimum + static_cast<double>(config.dimensions[axis] - 1) * config.voxelSizeMetres;
        const auto value = axis == 0 ? point.x : (axis == 1 ? point.y : point.z);
        const auto epsilon = config.voxelSizeMetres * epsilonScale;
        if (std::abs(static_cast<double>(value) - minimum) <= epsilon ||
            std::abs(static_cast<double>(value) - maximum) <= epsilon)
            return true;
    }
    return false;
}

Topology analyzeTopology(const aether::mesh::MeshAsset& mesh,
                         const aether::reconstruction::DenseTsdfConfig& config) {
    Topology result;
    std::size_t base = 0;
    struct EdgeUse final {
        std::size_t count{};
        bool onBoundary{};
    };
    std::map<std::pair<std::size_t, std::size_t>, EdgeUse> edges;
    std::size_t totalVertices = 0;
    for (const auto& primitive : mesh.primitives)
        totalVertices += primitive.vertices.size();
    DisjointSet sets(totalVertices);
    std::vector<bool> used(totalVertices);

    for (const auto& primitive : mesh.primitives) {
        require(primitive.indices.size() % 3 == 0, "mesh index count must be divisible by three");
        result.vertices += primitive.vertices.size();
        result.triangles += primitive.indices.size() / 3;
        for (std::size_t index = 0; index < primitive.indices.size(); index += 3) {
            std::array<std::size_t, 3> triangle{
                base + primitive.indices[index],
                base + primitive.indices[index + 1],
                base + primitive.indices[index + 2],
            };
            for (const auto vertex : triangle)
                require(vertex < base + primitive.vertices.size(),
                        "mesh contains an invalid index");
            require(triangle[0] != triangle[1] && triangle[1] != triangle[2] &&
                        triangle[0] != triangle[2],
                    "mesh contains a repeated triangle index");
            for (std::size_t edge = 0; edge < 3; ++edge) {
                auto left = triangle[edge];
                auto right = triangle[(edge + 1) % 3];
                sets.join(left, right);
                used[left] = true;
                used[right] = true;
                if (left > right)
                    std::swap(left, right);
                const auto localLeft = left - base;
                const auto localRight = right - base;
                auto& use = edges[{left, right}];
                ++use.count;
                use.onBoundary = onVolumeBoundary(config, primitive.vertices[localLeft].position) &&
                                 onVolumeBoundary(config, primitive.vertices[localRight].position);
            }
        }
        base += primitive.vertices.size();
    }

    for (const auto& [edge, use] : edges) {
        static_cast<void>(edge);
        if (use.count == 1) {
            ++result.boundaryEdges;
            if (!use.onBoundary)
                ++result.interiorBoundaryEdges;
        } else if (use.count > 2) {
            ++result.nonManifoldEdges;
        }
    }
    std::vector<std::size_t> roots;
    for (std::size_t vertex = 0; vertex < used.size(); ++vertex)
        if (used[vertex])
            roots.push_back(sets.find(vertex));
    std::sort(roots.begin(), roots.end());
    roots.erase(std::unique(roots.begin(), roots.end()), roots.end());
    result.connectedComponents = roots.size();
    result.eulerCharacteristic = static_cast<std::int64_t>(result.vertices) -
                                 static_cast<std::int64_t>(edges.size()) +
                                 static_cast<std::int64_t>(result.triangles);
    return result;
}

FixtureResult evaluateFixture(const std::string& name, const std::string& extractor,
                              const aether::mesh::MeshAsset& mesh,
                              const aether::reconstruction::DenseTsdfConfig& config,
                              const Field& field) {
    std::vector<double> errors;
    for (const auto& primitive : mesh.primitives) {
        for (const auto& vertex : primitive.vertices) {
            errors.push_back(
                std::abs(field(vertex.position.x, vertex.position.y, vertex.position.z)));
            const auto length = simd_length(vertex.normal);
            require(std::isfinite(length) && std::abs(length - 1.0F) <= 1.0e-4F,
                    "extracted normals must be finite and normalized");
        }
    }
    require(!errors.empty(), "fixture extraction produced no vertices");
    std::sort(errors.begin(), errors.end());
    const auto p95Index =
        static_cast<std::size_t>(std::ceil(0.95 * static_cast<double>(errors.size())) - 1.0);
    FixtureResult result;
    result.name = name;
    result.extractor = extractor;
    result.voxelSizeMetres = config.voxelSizeMetres;
    result.meanSurfaceErrorMetres =
        std::accumulate(errors.begin(), errors.end(), 0.0) / static_cast<double>(errors.size());
    result.p95SurfaceErrorMetres = errors[std::min(p95Index, errors.size() - 1)];
    result.maximumSurfaceErrorMetres = errors.back();
    result.topology = analyzeTopology(mesh, config);
    return result;
}

void verifyClassicCaseTable() {
    constexpr std::array<std::array<int, 2>, 12> edgeCorners{{
        {{0, 1}},
        {{3, 2}},
        {{4, 5}},
        {{7, 6}},
        {{0, 3}},
        {{1, 2}},
        {{4, 7}},
        {{5, 6}},
        {{0, 4}},
        {{1, 5}},
        {{3, 7}},
        {{2, 6}},
    }};
    for (std::uint16_t caseIndex = 0; caseIndex < 256; ++caseIndex) {
        const auto& triangles = aether::reconstruction::ReferenceMarchingCubes::caseTriangles(
            static_cast<std::uint8_t>(caseIndex));
        std::size_t entries = 0;
        bool terminated = false;
        for (const auto edge : triangles) {
            if (edge < 0) {
                terminated = true;
                continue;
            }
            require(!terminated, "classic case table has entries after its terminator");
            require(edge < 12, "classic case table references an invalid edge");
            const auto corners = edgeCorners[static_cast<std::uint8_t>(edge)];
            const auto leftInside = (caseIndex & (1U << corners[0])) != 0;
            const auto rightInside = (caseIndex & (1U << corners[1])) != 0;
            require(leftInside != rightInside,
                    "classic case table references an edge without a zero crossing");
            ++entries;
        }
        require(entries % 3 == 0 && entries <= 15,
                "classic case table must contain at most five complete triangles");
        require((caseIndex == 0 || caseIndex == 255) == (entries == 0),
                "only empty and full classic cases may have no triangles");

        aether::reconstruction::DenseTsdfConfig config;
        config.dimensions = {2, 2, 2};
        config.originMetres = {0.0, 0.0, 0.0};
        config.voxelSizeMetres = 1.0;
        config.truncationDistanceMetres = 1.0;
        std::vector<aether::reconstruction::TsdfVoxel> voxels(8);
        constexpr std::array<std::array<std::uint32_t, 3>, 8> offsets{{
            {{0, 0, 0}},
            {{1, 0, 0}},
            {{1, 1, 0}},
            {{0, 1, 0}},
            {{0, 0, 1}},
            {{1, 0, 1}},
            {{1, 1, 1}},
            {{0, 1, 1}},
        }};
        for (std::size_t corner = 0; corner < offsets.size(); ++corner) {
            const auto& offset = offsets[corner];
            auto& voxel = voxels[gridIndex(config, offset[0], offset[1], offset[2])];
            voxel.distance = (caseIndex & (1U << corner)) != 0 ? -1.0F : 1.0F;
            voxel.weight = 1.0F;
        }
        auto reference = aether::reconstruction::ReferenceMarchingCubes::extract(config, voxels);
        if (caseIndex == 0 || caseIndex == 255) {
            require(!reference, "empty and full cases must not emit reference geometry");
        } else {
            require(reference.has_value(), "every non-trivial classic case must extract");
            require(reference->primitives[0].indices.size() == entries,
                    "reference extractor triangle count must match the classic case table");
            auto volume = aether::reconstruction::DenseTsdfVolume::fromScalarField(config, voxels);
            require(volume.has_value(), "every non-trivial production case field must be valid");
            auto production = volume->extractMesh();
            require(production.has_value(), "every non-trivial production case must extract");
            const auto topology = analyzeTopology(*production, config);
            require(topology.interiorBoundaryEdges == 0 && topology.nonManifoldEdges == 0,
                    "single-cell production case must be locally manifold without interior cracks");
        }
    }
}

AmbiguityResult verifyAmbiguousSharedFace() {
    aether::reconstruction::DenseTsdfConfig config;
    config.dimensions = {5, 5, 5};
    config.originMetres = {-0.02, -0.02, -0.02};
    config.voxelSizeMetres = 0.01;
    config.truncationDistanceMetres = 0.04;
    std::vector<aether::reconstruction::TsdfVoxel> voxels(125);
    for (auto& voxel : voxels) {
        voxel.distance = 1.0F;
        voxel.weight = 1.0F;
    }
    voxels[gridIndex(config, 2, 1, 1)].distance = -0.5F;
    voxels[gridIndex(config, 2, 2, 2)].distance = -0.5F;

    auto volume = aether::reconstruction::DenseTsdfVolume::fromScalarField(config, voxels);
    require(volume.has_value(), "embedded ambiguous-face field must be valid");
    auto production = volume->extractMesh();
    auto reference = aether::reconstruction::ReferenceMarchingCubes::extract(config, voxels);
    require(production.has_value() && reference.has_value(),
            "both extractors must resolve the embedded ambiguous-face field");
    AmbiguityResult result{
        .production = analyzeTopology(*production, config),
        .reference = analyzeTopology(*reference, config),
    };
    for (const auto* topology : {&result.production, &result.reference})
        require(topology->boundaryEdges == 0 && topology->nonManifoldEdges == 0,
                "embedded ambiguous face must remain closed and manifold");
    return result;
}

std::string toJson(std::span<const FixtureResult> results, const AmbiguityResult& ambiguity) {
    std::ostringstream output;
    output << std::setprecision(12);
    output << "{\n  \"schemaVersion\": 1,\n"
              "  \"evidenceLevel\": \"E2\",\n"
              "  \"caseTableCases\": 256,\n"
              "  \"productionCasesExtracted\": 254,\n"
              "  \"ambiguousSharedFace\": {\n"
           << "    \"productionBoundaryEdges\": " << ambiguity.production.boundaryEdges << ",\n"
           << "    \"productionNonManifoldEdges\": " << ambiguity.production.nonManifoldEdges
           << ",\n"
           << "    \"referenceBoundaryEdges\": " << ambiguity.reference.boundaryEdges << ",\n"
           << "    \"referenceNonManifoldEdges\": " << ambiguity.reference.nonManifoldEdges << "\n"
           << "  },\n"
              "  \"fixtures\": [\n";
    for (std::size_t index = 0; index < results.size(); ++index) {
        const auto& result = results[index];
        output << "    {\n"
               << "      \"name\": \"" << result.name << "\",\n"
               << "      \"extractor\": \"" << result.extractor << "\",\n"
               << "      \"voxelSizeMetres\": " << result.voxelSizeMetres << ",\n"
               << "      \"meanSurfaceErrorMetres\": " << result.meanSurfaceErrorMetres << ",\n"
               << "      \"p95SurfaceErrorMetres\": " << result.p95SurfaceErrorMetres << ",\n"
               << "      \"maximumSurfaceErrorMetres\": " << result.maximumSurfaceErrorMetres
               << ",\n"
               << "      \"vertices\": " << result.topology.vertices << ",\n"
               << "      \"triangles\": " << result.topology.triangles << ",\n"
               << "      \"boundaryEdges\": " << result.topology.boundaryEdges << ",\n"
               << "      \"interiorBoundaryEdges\": " << result.topology.interiorBoundaryEdges
               << ",\n"
               << "      \"nonManifoldEdges\": " << result.topology.nonManifoldEdges << ",\n"
               << "      \"connectedComponents\": " << result.topology.connectedComponents << ",\n"
               << "      \"eulerCharacteristic\": " << result.topology.eulerCharacteristic << "\n"
               << "    }" << (index + 1 == results.size() ? "\n" : ",\n");
    }
    output << "  ]\n}\n";
    return output.str();
}

} // namespace

int main(int argc, char** argv) {
    try {
        std::optional<std::filesystem::path> outputPath;
        if (argc == 3 && std::string_view(argv[1]) == "--json-output")
            outputPath = argv[2];
        else if (argc != 1)
            throw std::runtime_error("usage: AetherOracleGeometryTests [--json-output PATH]");

        verifyClassicCaseTable();
        const auto ambiguity = verifyAmbiguousSharedFace();

        aether::reconstruction::DenseTsdfConfig config;
        config.dimensions = {65, 65, 65};
        config.originMetres = {-0.32, -0.32, -0.32};
        config.voxelSizeMetres = 0.01;
        config.truncationDistanceMetres = 0.04;

        const Field sphere = [](double x, double y, double z) {
            return std::sqrt(x * x + y * y + z * z) - 0.2;
        };
        const Field box = [](double x, double y, double z) {
            const auto qx = std::abs(x) - 0.2;
            const auto qy = std::abs(y) - 0.16;
            const auto qz = std::abs(z) - 0.12;
            const auto outside = std::sqrt(std::max(qx, 0.0) * std::max(qx, 0.0) +
                                           std::max(qy, 0.0) * std::max(qy, 0.0) +
                                           std::max(qz, 0.0) * std::max(qz, 0.0));
            return outside + std::min(std::max(qx, std::max(qy, qz)), 0.0);
        };
        const Field thinWall = [](double x, double y, double z) {
            const auto qx = std::abs(x) - 0.22;
            const auto qy = std::abs(y) - 0.18;
            const auto qz = std::abs(z) - 0.015;
            const auto outside = std::sqrt(std::max(qx, 0.0) * std::max(qx, 0.0) +
                                           std::max(qy, 0.0) * std::max(qy, 0.0) +
                                           std::max(qz, 0.0) * std::max(qz, 0.0));
            return outside + std::min(std::max(qx, std::max(qy, qz)), 0.0);
        };
        const Field twoSpheres = [](double x, double y, double z) {
            const auto left = std::sqrt((x + 0.14) * (x + 0.14) + y * y + z * z) - 0.09;
            const auto right = std::sqrt((x - 0.14) * (x - 0.14) + y * y + z * z) - 0.09;
            return std::min(left, right);
        };
        const Field torus = [](double x, double y, double z) {
            const auto radial = std::sqrt(x * x + y * y) - 0.16;
            return std::sqrt(radial * radial + z * z) - 0.065;
        };

        struct Fixture final {
            const char* name;
            Field field;
            std::size_t components;
            std::int64_t euler;
        };
        const std::array fixtures{
            Fixture{"sphere", sphere, 1, 2},         Fixture{"box", box, 1, 2},
            Fixture{"thin-wall", thinWall, 1, 2},    Fixture{"two-spheres", twoSpheres, 2, 4},
            Fixture{"torus-ambiguous", torus, 1, 0},
        };

        std::vector<FixtureResult> results;
        for (const auto& fixture : fixtures) {
            const auto voxels = makeField(config, fixture.field);
            auto volume = aether::reconstruction::DenseTsdfVolume::fromScalarField(config, voxels);
            require(volume.has_value(), std::string(fixture.name) + " scalar field is valid");
            auto production = volume->extractMesh();
            auto reference =
                aether::reconstruction::ReferenceMarchingCubes::extract(config, voxels);
            require(production.has_value(), std::string(fixture.name) + " production extraction");
            require(reference.has_value(), std::string(fixture.name) + " reference extraction");

            auto productionResult = evaluateFixture(fixture.name, "resolved-production",
                                                    *production, config, fixture.field);
            auto referenceResult = evaluateFixture(fixture.name, "classic-reference", *reference,
                                                   config, fixture.field);
            for (const auto* result : {&productionResult, &referenceResult}) {
                require(result->p95SurfaceErrorMetres <= config.voxelSizeMetres,
                        result->name + " p95 surface error exceeds one voxel");
                require(result->topology.boundaryEdges == 0,
                        result->name + " closed fixture has boundary edges");
                require(result->topology.nonManifoldEdges == 0,
                        result->name + " fixture has non-manifold edges");
                require(result->topology.connectedComponents == fixture.components,
                        result->name + " component count is wrong");
                require(result->topology.eulerCharacteristic == fixture.euler,
                        result->name + " Euler characteristic is wrong");
            }
            results.push_back(std::move(productionResult));
            results.push_back(std::move(referenceResult));
        }

        const auto json = toJson(results, ambiguity);
        if (outputPath) {
            std::filesystem::create_directories(outputPath->parent_path());
            std::ofstream output(*outputPath, std::ios::binary | std::ios::trunc);
            require(static_cast<bool>(output), "could not open geometry report output");
            output << json;
            require(static_cast<bool>(output), "could not write geometry report output");
        }
        std::cout << json;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Oracle geometry verification failed: " << error.what() << '\n';
        return 1;
    }
}
