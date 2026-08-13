#include <aether/reconstruction/IncrementalSparseTsdfMesher.hpp>

#include <algorithm>
#include <array>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <utility>

namespace aether::reconstruction {
namespace {

std::array<std::uint32_t, 3> blockCounts(const SparseTsdfConfig& config) {
    const auto blocks = [&](std::uint32_t dimension) {
        return static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(dimension) + config.blockResolution - 1) /
            config.blockResolution);
    };
    return {blocks(config.volume.dimensions[0]), blocks(config.volume.dimensions[1]),
            blocks(config.volume.dimensions[2])};
}

Result<std::size_t> checkedVoxelCount(const std::array<std::uint32_t, 3>& dimensions,
                                      std::size_t budget) {
    std::size_t count = 1;
    for (const auto dimension : dimensions) {
        if (dimension < 2 || count > budget / dimension)
            return fail(ErrorCode::resourceExhausted,
                        "Incremental sparse TSDF patch exceeds its voxel budget");
        count *= dimension;
    }
    return count;
}

} // namespace

Result<IncrementalSparseTsdfMesher>
IncrementalSparseTsdfMesher::create(IncrementalSparseMesherConfig config) {
    if (config.maximumPatchesPerUpdate == 0 || config.maximumPatchVoxels < 8)
        return fail(ErrorCode::invalidArgument, "Incremental sparse mesher budgets are invalid");
    return IncrementalSparseTsdfMesher(config);
}

Result<std::vector<SparseMeshPatchUpdate>>
IncrementalSparseTsdfMesher::update(const SparseTsdfSnapshot& snapshot,
                                    std::span<const TsdfBlockCoordinate> dirtyBlocks) {
    if (auto validated = SparseTsdfVolume::create(snapshot.config); !validated)
        return std::unexpected(validated.error());
    if (snapshot.generation < generation_)
        return fail(ErrorCode::invalidArgument, "Incremental sparse mesher snapshot is stale");
    if (dirtyBlocks.empty())
        return fail(ErrorCode::invalidArgument, "Incremental sparse mesher has no dirty blocks");

    const auto counts = blockCounts(snapshot.config);
    const std::size_t voxelsPerBlock = static_cast<std::size_t>(snapshot.config.blockResolution) *
                                       snapshot.config.blockResolution *
                                       snapshot.config.blockResolution;
    std::map<TsdfBlockCoordinate, const std::vector<TsdfVoxel>*> blocks;
    for (const auto& block : snapshot.blocks) {
        if (block.coordinate.x >= counts[0] || block.coordinate.y >= counts[1] ||
            block.coordinate.z >= counts[2] || block.voxels.size() != voxelsPerBlock ||
            blocks.contains(block.coordinate))
            return fail(ErrorCode::corruptData, "Sparse TSDF snapshot block is invalid");
        blocks.emplace(block.coordinate, &block.voxels);
    }

    std::set<TsdfBlockCoordinate> owners;
    for (const auto dirty : dirtyBlocks) {
        if (dirty.x >= counts[0] || dirty.y >= counts[1] || dirty.z >= counts[2])
            return fail(ErrorCode::invalidArgument, "Dirty sparse TSDF block is out of bounds");
        for (std::uint32_t dz = 0; dz <= 1; ++dz)
            for (std::uint32_t dy = 0; dy <= 1; ++dy)
                for (std::uint32_t dx = 0; dx <= 1; ++dx) {
                    if (dirty.x < dx || dirty.y < dy || dirty.z < dz)
                        continue;
                    owners.insert({dirty.x - dx, dirty.y - dy, dirty.z - dz});
                }
    }
    if (owners.size() > config_.maximumPatchesPerUpdate)
        return fail(ErrorCode::resourceExhausted,
                    "Incremental sparse TSDF update exceeds its patch budget");

    std::vector<SparseMeshPatchUpdate> updates;
    updates.reserve(owners.size());
    for (const auto owner : owners) {
        const std::array<std::uint64_t, 3> ownedFirst{
            static_cast<std::uint64_t>(owner.x) * snapshot.config.blockResolution,
            static_cast<std::uint64_t>(owner.y) * snapshot.config.blockResolution,
            static_cast<std::uint64_t>(owner.z) * snapshot.config.blockResolution};
        std::array<std::uint64_t, 3> ownedEnd{};
        std::array<std::uint64_t, 3> fieldFirst{};
        std::array<std::uint64_t, 3> fieldLast{};
        std::array<std::uint32_t, 3> dimensions{};
        std::array<std::uint32_t, 3> firstCell{};
        std::array<std::uint32_t, 3> onePastLastCell{};
        bool ownsCells = true;
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const auto maximumCell =
                static_cast<std::uint64_t>(snapshot.config.volume.dimensions[axis] - 1);
            ownedEnd[axis] =
                std::min(ownedFirst[axis] + snapshot.config.blockResolution, maximumCell);
            ownsCells = ownsCells && ownedFirst[axis] < ownedEnd[axis];
            fieldFirst[axis] = ownedFirst[axis] == 0 ? 0 : ownedFirst[axis] - 1;
            fieldLast[axis] = std::min(ownedEnd[axis] + 1, maximumCell);
            dimensions[axis] = static_cast<std::uint32_t>(fieldLast[axis] - fieldFirst[axis] + 1);
            firstCell[axis] = static_cast<std::uint32_t>(ownedFirst[axis] - fieldFirst[axis]);
            onePastLastCell[axis] = static_cast<std::uint32_t>(ownedEnd[axis] - fieldFirst[axis]);
        }
        if (!ownsCells) {
            updates.push_back({owner, snapshot.generation, std::nullopt});
            continue;
        }
        auto voxelCount = checkedVoxelCount(dimensions, config_.maximumPatchVoxels);
        if (!voxelCount)
            return std::unexpected(voxelCount.error());
        std::vector<TsdfVoxel> field(*voxelCount);
        const auto fieldIndex = [&](std::uint32_t x, std::uint32_t y, std::uint32_t z) {
            return (static_cast<std::size_t>(z) * dimensions[1] + y) * dimensions[0] + x;
        };
        for (std::uint32_t z = 0; z < dimensions[2]; ++z)
            for (std::uint32_t y = 0; y < dimensions[1]; ++y)
                for (std::uint32_t x = 0; x < dimensions[0]; ++x) {
                    const std::array<std::uint64_t, 3> global{fieldFirst[0] + x, fieldFirst[1] + y,
                                                              fieldFirst[2] + z};
                    const TsdfBlockCoordinate source{
                        static_cast<std::uint32_t>(global[0] / snapshot.config.blockResolution),
                        static_cast<std::uint32_t>(global[1] / snapshot.config.blockResolution),
                        static_cast<std::uint32_t>(global[2] / snapshot.config.blockResolution)};
                    const auto found = blocks.find(source);
                    if (found == blocks.end())
                        continue;
                    const auto lx =
                        static_cast<std::uint32_t>(global[0] % snapshot.config.blockResolution);
                    const auto ly =
                        static_cast<std::uint32_t>(global[1] % snapshot.config.blockResolution);
                    const auto lz =
                        static_cast<std::uint32_t>(global[2] % snapshot.config.blockResolution);
                    const auto sourceIndex =
                        (static_cast<std::size_t>(lz) * snapshot.config.blockResolution + ly) *
                            snapshot.config.blockResolution +
                        lx;
                    field[fieldIndex(x, y, z)] = (*found->second)[sourceIndex];
                }

        auto denseConfig = snapshot.config.volume;
        denseConfig.dimensions = dimensions;
        for (std::size_t axis = 0; axis < 3; ++axis)
            denseConfig.originMetres[axis] +=
                static_cast<double>(fieldFirst[axis]) * denseConfig.voxelSizeMetres;
        auto dense = DenseTsdfVolume::fromScalarField(denseConfig, field);
        if (!dense)
            return std::unexpected(dense.error());
        auto extracted = dense->extractMeshCells(firstCell, onePastLastCell);
        SparseMeshPatchUpdate update{owner, snapshot.generation, std::nullopt};
        if (extracted) {
            if (extracted->primitives.size() != 1)
                return fail(ErrorCode::internal,
                            "Incremental sparse mesher produced invalid patch");
            update.primitive = std::move(extracted->primitives.front());
            update.primitive->name = "tsdf-patch-" + std::to_string(owner.x) + "-" +
                                     std::to_string(owner.y) + "-" + std::to_string(owner.z);
        } else if (extracted.error().code != ErrorCode::notFound) {
            return std::unexpected(extracted.error());
        }
        updates.push_back(std::move(update));
    }

    for (const auto& update : updates) {
        if (update.primitive)
            patches_[update.coordinate] = *update.primitive;
        else
            patches_.erase(update.coordinate);
    }
    generation_ = snapshot.generation;
    return updates;
}

mesh::MeshAsset IncrementalSparseTsdfMesher::mesh() const {
    mesh::MeshAsset result;
    result.name = "incremental-sparse-tsdf";
    result.primitives.reserve(patches_.size());
    for (const auto& [coordinate, primitive] : patches_) {
        static_cast<void>(coordinate);
        result.primitives.push_back(primitive);
    }
    return result;
}

} // namespace aether::reconstruction
