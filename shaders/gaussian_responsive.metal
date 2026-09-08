// Responsive editor Gaussian path. Projection adds conservative early rejection and preserves
// canonical IDs through spatial preview reordering. Key generation packs tile + quantized positive
// depth into key.x so reduced-density interaction can sort the preview in half as many radix passes.
#define aetherGaussianProject aetherGaussianProjectReference
#define aetherGaussianGenerateKeys aetherGaussianGenerateKeysReference
#include "gaussian.metal"
#undef aetherGaussianGenerateKeys
#undef aetherGaussianProject

kernel void aetherGaussianProject(device const AetherGaussianGpu* gaussians [[buffer(0)]],
                                  constant AetherGaussianCamera& camera [[buffer(1)]],
                                  device AetherProjectedGaussian* projected [[buffer(2)]],
                                  device atomic_uint* counters [[buffer(3)]],
                                  device uint* tileCounts [[buffer(4)]],
                                  uint index [[thread_position_in_grid]]) {
    if (index >= camera.tileGridCounts.z)
        return;

    AetherProjectedGaussian output{};
    const AetherGaussianGpu gaussian = gaussians[index];
    // GaussianPipeline stores the canonical source index bit-exactly in dc.w. This lets the
    // viewport reorder large assets spatially while picking/debug IDs remain stable.
    const uint sourceIndex = as_type<uint>(gaussian.dc.w);
    output.sourceCountValid.x = sourceIndex;
    const float4 cameraPoint4 = camera.worldToCamera * float4(gaussian.positionOpacity.xyz, 1.0f);
    const float3 cameraPoint = cameraPoint4.xyz;
    if (cameraPoint.z < camera.depthViewport.x || cameraPoint.z > camera.depthViewport.y) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const float opacity =
        1.0f / (1.0f + exp(-clamp(gaussian.positionOpacity.w, -30.0f, 30.0f)));
    // Contributions below the 8-bit alpha floor cannot survive the compositor's own cutoff.
    if (opacity < 1.0f / 512.0f) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const float inverseZ = 1.0f / cameraPoint.z;
    const float2 center = float2(camera.focalCenter.x * cameraPoint.x * inverseZ +
                                     camera.focalCenter.z,
                                 camera.focalCenter.y * cameraPoint.y * inverseZ +
                                     camera.focalCenter.w);
    const float2 viewport = camera.depthViewport.zw;
    const float3 scales = exp(gaussian.logScaleRestCount.xyz);
    const float maximumScale = max(scales.x, max(scales.y, scales.z));
    const float focalMaximum = max(camera.focalCenter.x, camera.focalCenter.y);
    const float approximateRadius = 3.0f * focalMaximum * maximumScale * inverseZ;

    // This is deliberately conservative: use a generous bound so only splats that cannot touch
    // the viewport are rejected before covariance construction.
    const float conservativeRadius = max(1.0f, approximateRadius * 1.75f + 2.0f);
    if (center.x + conservativeRadius < 0.0f || center.y + conservativeRadius < 0.0f ||
        center.x - conservativeRadius >= viewport.x || center.y - conservativeRadius >= viewport.y) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    // Sub-pixel, low-opacity splats are expensive to sort but contribute negligibly during motion.
    // Larger or opaque splats always continue through the exact covariance path.
    if (approximateRadius < 0.32f && opacity < 0.20f) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const float3 variances = scales * scales;
    const float3x3 rotation = aetherQuaternionRotation(normalize(gaussian.rotation));
    const float3x3 worldCovariance = rotation * float3x3(variances.x, 0.0f, 0.0f, 0.0f,
                                                         variances.y, 0.0f, 0.0f, 0.0f,
                                                         variances.z) *
                                     transpose(rotation);
    const float3x3 cameraRotation = float3x3(camera.worldToCamera[0].xyz,
                                             camera.worldToCamera[1].xyz,
                                             camera.worldToCamera[2].xyz);
    const float3x3 covariance =
        cameraRotation * worldCovariance * transpose(cameraRotation);
    const float3 jacobianX = float3(camera.focalCenter.x * inverseZ, 0.0f,
                                    -camera.focalCenter.x * cameraPoint.x * inverseZ * inverseZ);
    const float3 jacobianY = float3(0.0f, camera.focalCenter.y * inverseZ,
                                    -camera.focalCenter.y * cameraPoint.y * inverseZ * inverseZ);
    const float a = dot(jacobianX, covariance * jacobianX) + 0.3f;
    const float b = dot(jacobianX, covariance * jacobianY);
    const float c = dot(jacobianY, covariance * jacobianY) + 0.3f;
    const float determinant = a * c - b * b;
    if (!isfinite(determinant) || determinant <= 1.0e-12f) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const float discriminant = sqrt(max(0.0f, (a - c) * (a - c) + 4.0f * b * b));
    const float radius = 3.0f * sqrt(0.5f * (a + c + discriminant));
    if (!isfinite(radius) || radius <= 0.0f || center.x + radius < 0.0f ||
        center.y + radius < 0.0f || center.x - radius >= viewport.x ||
        center.y - radius >= viewport.y) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const int2 minimumPixel = max(int2(0), int2(floor(center - radius)));
    const int2 maximumPixel = min(int2(viewport) - 1, int2(ceil(center + radius)));
    const uint2 minimumTile = uint2(minimumPixel) / aetherGaussianTileSize;
    const uint2 maximumTile = uint2(maximumPixel) / aetherGaussianTileSize;
    const uint overlap = (maximumTile.x - minimumTile.x + 1) *
                         (maximumTile.y - minimumTile.y + 1);

    output.centerDepthRadius = float4(center, cameraPoint.z, radius);
    output.conicOpacity = float4(c / determinant, -b / determinant, a / determinant, opacity);
    output.color = float4(
        aetherEvaluateSphericalHarmonics(gaussians[index], camera.cameraWorldPosition.xyz), 1.0f);
    output.tileBounds = uint4(minimumTile, maximumTile);
    const uint restCount = uint(max(gaussian.logScaleRestCount.w, 0.0f));
    const uint shDegree = restCount >= 45u ? 3u : restCount >= 24u ? 2u : restCount >= 9u ? 1u : 0u;
    output.sourceCountValid = uint4(sourceIndex, overlap, 1, shDegree);
    projected[index] = output;
    tileCounts[index] = overlap;
    atomic_fetch_add_explicit(&counters[0], 1, memory_order_relaxed);
}

kernel void aetherGaussianGenerateKeys(
    device const AetherProjectedGaussian* projected [[buffer(0)]],
    device const uint* offsets [[buffer(1)]], device uint2* keys [[buffer(2)]],
    device uint* values [[buffer(3)]], constant AetherGaussianCamera& camera [[buffer(4)]],
    uint index [[thread_position_in_grid]]) {
    if (index >= camera.tileGridCounts.z || projected[index].sourceCountValid.z == 0)
        return;

    const AetherProjectedGaussian gaussian = projected[index];
    uint destination = offsets[index];

    // 18 tile bits support up to 262,144 tiles (well beyond a 4K viewport's ~32K 16x16 tiles).
    // The remaining 14 bits keep the high-order IEEE-754 bits of positive camera depth. Positive
    // float bit patterns are monotonic with depth, so this remains front-to-back while accepting
    // coarser depth precision only in the interactive preview sorter.
    constexpr uint depthBits = 14u;
    constexpr uint depthMask = (1u << depthBits) - 1u;
    const uint positiveDepthBits = as_type<uint>(gaussian.centerDepthRadius.z);
    const uint quantizedDepth = (positiveDepthBits >> (32u - depthBits)) & depthMask;

    for (uint tileY = gaussian.tileBounds.y; tileY <= gaussian.tileBounds.w; ++tileY) {
        for (uint tileX = gaussian.tileBounds.x; tileX <= gaussian.tileBounds.z; ++tileX) {
            if (destination < camera.tileGridCounts.w) {
                const uint tileId = tileY * camera.tileGridCounts.x + tileX;
                const uint packedTileDepth = (tileId << depthBits) | quantizedDepth;
                keys[destination] = uint2(packedTileDepth, tileId);
                values[destination] = index;
            }
            ++destination;
        }
    }
}