#pragma once

#include <aether/gaussian/GaussianAsset.hpp>
#include <aether/world/PersistentWorld.hpp>

#include <array>
#include <cstddef>
#include <span>

namespace aether::world_gaussian {

enum class GaussianEditBoxFace : std::size_t {
    minimumX = 0,
    maximumX = 1,
    minimumY = 2,
    maximumY = 3,
    minimumZ = 4,
    maximumZ = 5,
};

struct GaussianTailLocalityCertificate final {
    std::array<double, 6> faceDensityBounds{};
    double outsideDensityBound{};
    std::size_t beforeChangedGaussians{};
    std::size_t afterChangedGaussians{};
};

/// Certifies a uniform upper bound on the change of the additive 3D Gaussian
/// density field outside an axis-aligned edit volume.
///
/// Only changed primitives are supplied. Unchanged primitives cancel exactly.
/// For each of the six outside halfspaces, the function sums the closed-form
/// maximum old/new Gaussian tails in that halfspace. The maximum of those six
/// sums bounds |rho_after(x) - rho_before(x)| for every x outside the box.
///
/// This is a density-field certificate, not yet a rendered RGB/transmittance
/// certificate.
[[nodiscard]] Result<GaussianTailLocalityCertificate>
certifyGaussianDensityLocality(std::span<const gaussian::Gaussian> beforeChanged,
                               std::span<const gaussian::Gaussian> afterChanged,
                               const world::Bounds& editVolume);

} // namespace aether::world_gaussian
