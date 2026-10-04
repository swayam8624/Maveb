#include "shared/AetherShaderTypes.h"
#include <metal_stdlib>

using namespace metal;

constant uint aetherGaussianTileSize = 16;

float3x3 aetherQuaternionRotation(float4 quaternion) {
    const float w = quaternion.x;
    const float x = quaternion.y;
    const float y = quaternion.z;
    const float z = quaternion.w;
    return float3x3(float3(1.0f - 2.0f * (y * y + z * z), 2.0f * (x * y + z * w),
                           2.0f * (x * z - y * w)),
                    float3(2.0f * (x * y - z * w), 1.0f - 2.0f * (x * x + z * z),
                           2.0f * (y * z + x * w)),
                    float3(2.0f * (x * z + y * w), 2.0f * (y * z - x * w),
                           1.0f - 2.0f * (x * x + y * y)));
}

float aetherGaussianRest(device const AetherGaussianGpu& gaussian, uint index) {
    return gaussian.shRest[index / 4][index & 3];
}

float3 aetherGaussianShCoefficient(device const AetherGaussianGpu& gaussian, uint index) {
    if (index == 0)
        return gaussian.dc.xyz;
    const uint rest = index - 1;
    return float3(aetherGaussianRest(gaussian, rest),
                  aetherGaussianRest(gaussian, 15 + rest),
                  aetherGaussianRest(gaussian, 30 + rest));
}

float3 aetherEvaluateSphericalHarmonics(device const AetherGaussianGpu& gaussian,
                                       float3 cameraWorldPosition) {
    constexpr float c0 = 0.28209479177387814f;
    constexpr float c1 = 0.4886025119029199f;
    const float3 direction = normalize(gaussian.positionOpacity.xyz - cameraWorldPosition);
    const float x = direction.x;
    const float y = direction.y;
    const float z = direction.z;
    float3 result = c0 * aetherGaussianShCoefficient(gaussian, 0);
    const uint restCount = uint(gaussian.logScaleRestCount.w);
    if (restCount >= 9) {
        result += -c1 * y * aetherGaussianShCoefficient(gaussian, 1);
        result += c1 * z * aetherGaussianShCoefficient(gaussian, 2);
        result += -c1 * x * aetherGaussianShCoefficient(gaussian, 3);
        if (restCount >= 24) {
            constexpr float c2[] = {1.0925484305920792f, -1.0925484305920792f,
                                    0.31539156525252005f, -1.0925484305920792f,
                                    0.5462742152960396f};
            const float xx = x * x;
            const float yy = y * y;
            const float zz = z * z;
            result += c2[0] * x * y * aetherGaussianShCoefficient(gaussian, 4);
            result += c2[1] * y * z * aetherGaussianShCoefficient(gaussian, 5);
            result += c2[2] * (2.0f * zz - xx - yy) *
                      aetherGaussianShCoefficient(gaussian, 6);
            result += c2[3] * x * z * aetherGaussianShCoefficient(gaussian, 7);
            result += c2[4] * (xx - yy) * aetherGaussianShCoefficient(gaussian, 8);
            if (restCount >= 45) {
                constexpr float c3[] = {-0.5900435899266435f, 2.890611442640554f,
                                        -0.4570457994644658f, 0.3731763325901154f,
                                        -0.4570457994644658f, 1.445305721320277f,
                                        -0.5900435899266435f};
                result += c3[0] * y * (3.0f * xx - yy) *
                          aetherGaussianShCoefficient(gaussian, 9);
                result += c3[1] * x * y * z * aetherGaussianShCoefficient(gaussian, 10);
                result += c3[2] * y * (4.0f * zz - xx - yy) *
                          aetherGaussianShCoefficient(gaussian, 11);
                result += c3[3] * z * (2.0f * zz - 3.0f * xx - 3.0f * yy) *
                          aetherGaussianShCoefficient(gaussian, 12);
                result += c3[4] * x * (4.0f * zz - xx - yy) *
                          aetherGaussianShCoefficient(gaussian, 13);
                result += c3[5] * z * (xx - yy) *
                          aetherGaussianShCoefficient(gaussian, 14);
                result += c3[6] * x * (xx - 3.0f * yy) *
                          aetherGaussianShCoefficient(gaussian, 15);
            }
        }
    }
    return max(result + 0.5f, 0.0f);
}

kernel void aetherGaussianProject(device const AetherGaussianGpu* gaussians [[buffer(0)]],
                                  constant AetherGaussianCamera& camera [[buffer(1)]],
                                  device AetherProjectedGaussian* projected [[buffer(2)]],
                                  device atomic_uint* counters [[buffer(3)]],
                                  device uint* tileCounts [[buffer(4)]],
                                  uint index [[thread_position_in_grid]]) {
    if (index >= camera.tileGridCounts.z)
        return;
    AetherProjectedGaussian output{};
    output.sourceCountValid.x = index;
    const AetherGaussianGpu gaussian = gaussians[index];
    const float4 cameraPoint4 = camera.worldToCamera * float4(gaussian.positionOpacity.xyz, 1.0f);
    const float3 cameraPoint = cameraPoint4.xyz;
    if (cameraPoint.z < camera.depthViewport.x || cameraPoint.z > camera.depthViewport.y) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }

    const float3 scales = exp(gaussian.logScaleRestCount.xyz);
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
    const float inverseZ = 1.0f / cameraPoint.z;
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
    const float2 center = float2(camera.focalCenter.x * cameraPoint.x * inverseZ +
                                     camera.focalCenter.z,
                                 camera.focalCenter.y * cameraPoint.y * inverseZ +
                                     camera.focalCenter.w);
    const float2 viewport = camera.depthViewport.zw;
    if (!isfinite(radius) || radius <= 0.0f || center.x + radius < 0.0f ||
        center.y + radius < 0.0f || center.x - radius >= viewport.x ||
        center.y - radius >= viewport.y) {
        projected[index] = output;
        tileCounts[index] = 0;
        return;
    }
    const int2 minimumPixel = max(int2(0), int2(floor(center - radius)));
    const int2 maximumPixel =
        min(int2(viewport) - 1, int2(ceil(center + radius)));
    const uint2 minimumTile = uint2(minimumPixel) / aetherGaussianTileSize;
    const uint2 maximumTile = uint2(maximumPixel) / aetherGaussianTileSize;
    const uint overlap = (maximumTile.x - minimumTile.x + 1) *
                         (maximumTile.y - minimumTile.y + 1);
    output.centerDepthRadius = float4(center, cameraPoint.z, radius);
    output.conicOpacity = float4(c / determinant, -b / determinant, a / determinant,
                                 1.0f / (1.0f + exp(-clamp(gaussian.positionOpacity.w, -30.0f,
                                                          30.0f))));
    output.color = float4(
        aetherEvaluateSphericalHarmonics(gaussians[index], camera.cameraWorldPosition.xyz), 1.0f);
    output.tileBounds = uint4(minimumTile, maximumTile);
    const uint restCount = uint(max(gaussian.logScaleRestCount.w, 0.0f));
    const uint shDegree = restCount >= 45u ? 3u : restCount >= 24u ? 2u : restCount >= 9u ? 1u : 0u;
    output.sourceCountValid = uint4(index, overlap, 1, shDegree);
    projected[index] = output;
    tileCounts[index] = overlap;
    atomic_fetch_add_explicit(&counters[0], 1, memory_order_relaxed);
}

kernel void aetherGaussianExclusiveScan(device const uint* counts [[buffer(0)]],
                                        device uint* offsets [[buffer(1)]],
                                        device atomic_uint* counters [[buffer(2)]],
                                        constant AetherGaussianCamera& camera [[buffer(3)]],
                                        device uint* indirectDispatch [[buffer(4)]],
                                        uint index [[thread_position_in_grid]]) {
    if (index != 0)
        return;
    uint total = 0;
    for (uint item = 0; item < camera.tileGridCounts.z; ++item) {
        offsets[item] = total;
        const uint next = total + counts[item];
        total = next < total ? camera.tileGridCounts.w : min(next, camera.tileGridCounts.w);
    }
    atomic_store_explicit(&counters[1], total, memory_order_relaxed);
    indirectDispatch[0] = (total + 255) / 256;
    indirectDispatch[1] = 1;
    indirectDispatch[2] = 1;
    uint requested = 0;
    if (camera.tileGridCounts.z > 0) {
        const uint last = camera.tileGridCounts.z - 1;
        requested = offsets[last] + counts[last];
    }
    if (requested > camera.tileGridCounts.w)
        atomic_store_explicit(&counters[2], requested - camera.tileGridCounts.w,
                              memory_order_relaxed);
}

kernel void aetherGaussianScanBlocks(device const uint* counts [[buffer(0)]],
                                     device uint* offsets [[buffer(1)]],
                                     device uint* blockSums [[buffer(2)]],
                                     constant AetherGaussianCamera& camera [[buffer(3)]],
                                     uint index [[thread_position_in_grid]],
                                     uint localIndex [[thread_index_in_threadgroup]],
                                     uint groupIndex [[threadgroup_position_in_grid]]) {
    threadgroup uint scratch[256];
    scratch[localIndex] = index < camera.tileGridCounts.z ? counts[index] : 0;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for (uint stride = 1; stride < 256; stride <<= 1) {
        const uint element = (localIndex + 1) * stride * 2 - 1;
        if (element < 256)
            scratch[element] += scratch[element - stride];
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (localIndex == 0) {
        blockSums[groupIndex] = scratch[255];
        scratch[255] = 0;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for (uint stride = 128; stride > 0; stride >>= 1) {
        const uint element = (localIndex + 1) * stride * 2 - 1;
        if (element < 256) {
            const uint previous = scratch[element - stride];
            scratch[element - stride] = scratch[element];
            scratch[element] += previous;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (index < camera.tileGridCounts.z)
        offsets[index] = scratch[localIndex];
}

kernel void aetherGaussianScanBlockSums(device uint* blockSums [[buffer(0)]],
                                        device atomic_uint* counters [[buffer(1)]],
                                        constant AetherGaussianCamera& camera [[buffer(2)]],
                                        device uint* indirectDispatch [[buffer(3)]],
                                        uint index [[thread_position_in_grid]]) {
    if (index != 0)
        return;
    const uint blockCount = (camera.tileGridCounts.z + 255) / 256;
    ulong total = 0;
    for (uint block = 0; block < blockCount; ++block) {
        const uint count = blockSums[block];
        blockSums[block] = uint(min(total, ulong(camera.tileGridCounts.w)));
        total += count;
    }
    const uint stored = uint(min(total, ulong(camera.tileGridCounts.w)));
    atomic_store_explicit(&counters[1], stored, memory_order_relaxed);
    indirectDispatch[0] = (stored + 255) / 256;
    indirectDispatch[1] = 1;
    indirectDispatch[2] = 1;
    if (total > camera.tileGridCounts.w) {
        atomic_store_explicit(&counters[2],
                              uint(min(total - camera.tileGridCounts.w, ulong(0xffffffffu))),
                              memory_order_relaxed);
    }
}

uint aetherGaussianRadixDigit(uint2 key, uint pass) {
    const uint component = pass < 8 ? key.x : key.y;
    return (component >> ((pass & 7) * 4)) & 15;
}

kernel void aetherGaussianRadixHistogram(
    device const uint2* keys [[buffer(0)]], device uint* groupHistograms [[buffer(1)]],
    device const atomic_uint* counters [[buffer(2)]], constant uint& pass [[buffer(3)]],
    uint index [[thread_position_in_grid]], uint localIndex [[thread_index_in_threadgroup]],
    uint groupIndex [[threadgroup_position_in_grid]], uint lane [[thread_index_in_simdgroup]],
    uint simdGroup [[simdgroup_index_in_threadgroup]], uint simdWidth [[threads_per_simdgroup]],
    uint threadsPerGroup [[threads_per_threadgroup]]) {
    threadgroup uint simdCounts[32][16];
    const uint count = atomic_load_explicit(&counters[1], memory_order_relaxed);
    const uint digit = index < count ? aetherGaussianRadixDigit(keys[index], pass) : 0xffffffffu;
    for (uint bucket = 0; bucket < 16; ++bucket) {
        const uint matches = digit == bucket ? 1 : 0;
        const uint total = simd_sum(matches);
        if (lane == 0)
            simdCounts[simdGroup][bucket] = total;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    const uint simdGroupCount = threadsPerGroup / simdWidth;
    if (localIndex < 16) {
        uint total = 0;
        for (uint group = 0; group < simdGroupCount; ++group)
            total += simdCounts[group][localIndex];
        groupHistograms[groupIndex * 16 + localIndex] = total;
    }
}

kernel void aetherGaussianRadixOffsets(device const uint* groupHistograms [[buffer(0)]],
                                       device uint* groupOffsets [[buffer(1)]],
                                       device const atomic_uint* counters [[buffer(2)]],
                                       uint index [[thread_position_in_grid]]) {
    if (index != 0)
        return;
    const uint count = atomic_load_explicit(&counters[1], memory_order_relaxed);
    const uint groupCount = (count + 255) / 256;
    uint base = 0;
    for (uint bucket = 0; bucket < 16; ++bucket) {
        for (uint group = 0; group < groupCount; ++group) {
            const uint location = group * 16 + bucket;
            groupOffsets[location] = base;
            base += groupHistograms[location];
        }
    }
}

kernel void aetherGaussianRadixScatter(
    device const uint2* inputKeys [[buffer(0)]], device const uint* inputValues [[buffer(1)]],
    device uint2* outputKeys [[buffer(2)]], device uint* outputValues [[buffer(3)]],
    device const uint* groupOffsets [[buffer(4)]],
    device const atomic_uint* counters [[buffer(5)]], constant uint& pass [[buffer(6)]],
    uint index [[thread_position_in_grid]], uint groupIndex [[threadgroup_position_in_grid]],
    uint lane [[thread_index_in_simdgroup]], uint simdGroup [[simdgroup_index_in_threadgroup]],
    uint simdWidth [[threads_per_simdgroup]], uint threadsPerGroup [[threads_per_threadgroup]]) {
    threadgroup uint simdCounts[32][16];
    const uint count = atomic_load_explicit(&counters[1], memory_order_relaxed);
    const uint digit = index < count ? aetherGaussianRadixDigit(inputKeys[index], pass) : 0xffffffffu;
    uint rankWithinSimd = 0;
    for (uint bucket = 0; bucket < 16; ++bucket) {
        const uint matches = digit == bucket ? 1 : 0;
        const uint prefix = simd_prefix_exclusive_sum(matches);
        const uint total = simd_sum(matches);
        if (lane == 0)
            simdCounts[simdGroup][bucket] = total;
        if (matches != 0)
            rankWithinSimd = prefix;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if (index >= count)
        return;
    uint localRank = rankWithinSimd;
    const uint simdGroupCount = threadsPerGroup / simdWidth;
    for (uint group = 0; group < min(simdGroup, simdGroupCount); ++group)
        localRank += simdCounts[group][digit];
    const uint destination = groupOffsets[groupIndex * 16 + digit] + localRank;
    outputKeys[destination] = inputKeys[index];
    outputValues[destination] = inputValues[index];
}

kernel void aetherGaussianAddBlockOffsets(device uint* offsets [[buffer(0)]],
                                          device const uint* blockSums [[buffer(1)]],
                                          constant AetherGaussianCamera& camera [[buffer(2)]],
                                          uint index [[thread_position_in_grid]]) {
    if (index < camera.tileGridCounts.z)
        offsets[index] += blockSums[index / 256];
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
    for (uint tileY = gaussian.tileBounds.y; tileY <= gaussian.tileBounds.w; ++tileY) {
        for (uint tileX = gaussian.tileBounds.x; tileX <= gaussian.tileBounds.z; ++tileX) {
            if (destination < camera.tileGridCounts.w) {
                keys[destination] = uint2(as_type<uint>(gaussian.centerDepthRadius.z),
                                          tileY * camera.tileGridCounts.x + tileX);
                values[destination] = index;
            }
            ++destination;
        }
    }
}

kernel void aetherGaussianStableRadixPass(
    device const uint2* inputKeys [[buffer(0)]], device const uint* inputValues [[buffer(1)]],
    device uint2* outputKeys [[buffer(2)]], device uint* outputValues [[buffer(3)]],
    device const atomic_uint* counters [[buffer(4)]], constant uint& pass [[buffer(5)]],
    uint index [[thread_position_in_grid]]) {
    if (index != 0)
        return;
    uint histogram[256];
    for (uint bucket = 0; bucket < 256; ++bucket)
        histogram[bucket] = 0;
    const uint count = atomic_load_explicit(&counters[1], memory_order_relaxed);
    const uint shift = (pass & 3) * 8;
    const uint component = pass >> 2;
    for (uint item = 0; item < count; ++item) {
        const uint key = component == 0 ? inputKeys[item].x : inputKeys[item].y;
        ++histogram[(key >> shift) & 255];
    }
    uint prefix = 0;
    for (uint bucket = 0; bucket < 256; ++bucket) {
        const uint frequency = histogram[bucket];
        histogram[bucket] = prefix;
        prefix += frequency;
    }
    for (uint item = 0; item < count; ++item) {
        const uint key = component == 0 ? inputKeys[item].x : inputKeys[item].y;
        const uint destination = histogram[(key >> shift) & 255]++;
        outputKeys[destination] = inputKeys[item];
        outputValues[destination] = inputValues[item];
    }
}

kernel void aetherGaussianInitializeRanges(device uint2* ranges [[buffer(0)]],
                                           constant AetherGaussianCamera& camera [[buffer(1)]],
                                           uint index [[thread_position_in_grid]]) {
    const uint tileCount = camera.tileGridCounts.x * camera.tileGridCounts.y;
    if (index < tileCount)
        ranges[index] = uint2(0xffffffffu, 0);
}

kernel void aetherGaussianBuildRanges(device const uint2* keys [[buffer(0)]],
                                      device uint2* ranges [[buffer(1)]],
                                      device const atomic_uint* counters [[buffer(2)]],
                                      uint index [[thread_position_in_grid]]) {
    if (index != 0)
        return;
    const uint count = atomic_load_explicit(&counters[1], memory_order_relaxed);
    if (count == 0)
        return;
    uint previousTile = keys[0].y;
    ranges[previousTile].x = 0;
    for (uint entry = 1; entry < count; ++entry) {
        const uint tile = keys[entry].y;
        if (tile != previousTile) {
            ranges[previousTile].y = entry;
            ranges[tile].x = entry;
            previousTile = tile;
        }
    }
    ranges[previousTile].y = count;
}

kernel void aetherGaussianComposite(
    device const AetherProjectedGaussian* projected [[buffer(0)]],
    device const uint* sortedValues [[buffer(1)]], device const uint2* ranges [[buffer(2)]],
    device atomic_uint* counters [[buffer(3)]], constant AetherGaussianCamera& camera [[buffer(4)]],
    texture2d<float, access::write> colorTarget [[texture(0)]],
    texture2d<float, access::write> depthTarget [[texture(1)]],
    texture2d<uint, access::write> idTarget [[texture(2)]],
    uint2 pixel [[thread_position_in_grid]]) {
    if (pixel.x >= uint(camera.depthViewport.z) || pixel.y >= uint(camera.depthViewport.w))
        return;
    const uint tile = (pixel.y / aetherGaussianTileSize) * camera.tileGridCounts.x +
                      pixel.x / aetherGaussianTileSize;
    const uint2 range = ranges[tile];
    float3 color = 0.0f;
    float opacity = 0.0f;
    float depth = INFINITY;
    float dominant = 0.0f;
    uint sourceId = 0;
    uint dominantShDegree = 0;
    float dominantSortRank = 0.0f;
    if (range.x != 0xffffffffu) {
        for (uint entry = range.x; entry < range.y; ++entry) {
            const AetherProjectedGaussian gaussian = projected[sortedValues[entry]];
            const float2 delta = float2(pixel) + 0.5f - gaussian.centerDepthRadius.xy;
            const float distance = gaussian.conicOpacity.x * delta.x * delta.x +
                                   2.0f * gaussian.conicOpacity.y * delta.x * delta.y +
                                   gaussian.conicOpacity.z * delta.y * delta.y;
            if (distance > 9.0f)
                continue;
            const float alpha = min(0.99f, gaussian.conicOpacity.w * exp(-0.5f * distance));
            if (alpha < 1.0f / 255.0f)
                continue;
            const float contribution = (1.0f - opacity) * alpha;
            color += contribution * gaussian.color.xyz;
            opacity += contribution;
            if (!isfinite(depth))
                depth = gaussian.centerDepthRadius.z;
            if (contribution > dominant) {
                dominant = contribution;
                sourceId = gaussian.sourceCountValid.x + 1;
                dominantShDegree = gaussian.sourceCountValid.w;
                dominantSortRank = range.y - range.x <= 1u
                                       ? 0.0f
                                       : float(entry - range.x) / float(range.y - range.x - 1u);
            }
            if (opacity > 0.999f) {
                atomic_fetch_add_explicit(&counters[3], 1, memory_order_relaxed);
                break;
            }
        }
    }
    const uint debugMode = camera.debugOptions.x;
    if (debugMode == 1) {
        const float normalizedDepth = isfinite(depth)
                                          ? log2(1.0f + depth) /
                                                log2(1.0f + camera.depthViewport.y)
                                          : 1.0f;
        color = 1.0f - normalizedDepth;
        opacity = 1.0f;
    } else if (debugMode == 2) {
        uint hash = sourceId * 747796405u + 2891336453u;
        hash = ((hash >> ((hash >> 28u) + 4u)) ^ hash) * 277803737u;
        hash = (hash >> 22u) ^ hash;
        color = sourceId == 0
                    ? float3(0.0f)
                    : float3(float(hash & 255u), float((hash >> 8u) & 255u),
                             float((hash >> 16u) & 255u)) /
                          255.0f;
        opacity = 1.0f;
    } else if (debugMode == 3) {
        const float occupancy = range.x == 0xffffffffu
                                    ? 0.0f
                                    : min(float(range.y - range.x) / 64.0f, 1.0f);
        color = float3(occupancy, occupancy * occupancy, 1.0f - occupancy);
        opacity = 1.0f;
    } else if (debugMode == 4) {
        color = opacity;
        opacity = 1.0f;
    } else if (debugMode == 5) {
        if (sourceId == 0u)
            color = float3(0.0f);
        else if (dominantShDegree == 0u)
            color = float3(0.15f, 0.25f, 1.0f);
        else if (dominantShDegree == 1u)
            color = float3(0.1f, 0.9f, 0.35f);
        else if (dominantShDegree == 2u)
            color = float3(1.0f, 0.75f, 0.1f);
        else
            color = float3(1.0f, 0.15f, 0.1f);
        opacity = 1.0f;
    } else if (debugMode == 6) {
        const float rank = dominantSortRank;
        color = sourceId == 0u
                    ? float3(0.0f)
                    : clamp(float3(1.5f - abs(4.0f * rank - 3.0f),
                                   1.5f - abs(4.0f * rank - 2.0f),
                                   1.5f - abs(4.0f * rank - 1.0f)), 0.0f, 1.0f);
        opacity = 1.0f;
    }
    colorTarget.write(float4(color, opacity), pixel);
    depthTarget.write(depth, pixel);
    idTarget.write(sourceId, pixel);
}
