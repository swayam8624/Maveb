#pragma once

#include <aether/core/Error.hpp>
#include <aether/mesh/MeshAsset.hpp>
#include <filesystem>

namespace aether::mesh {

/// Atomically writes validated world-space geometry to binary little-endian PLY.
Result<void> exportToPly(const MeshAsset& mesh, const std::filesystem::path& path);

} // namespace aether::mesh
