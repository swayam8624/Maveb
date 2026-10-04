#include "shared/AetherShaderTypes.h"
#include <metal_stdlib>

using namespace metal;

struct AetherTsdfSample {
    bool accepted;
    float normalizedDistance;
    float confidence;
    float3 color;
};

float3 aetherTsdfRotate(float4 quaternion, float3 value) {
    const float3 vector = quaternion.yzw;
    const float3 first = cross(vector, value);
    const float3 second = cross(vector, first);
    return value + 2.0f * (quaternion.x * first + second);
}

int aetherTsdfNearestPixel(float value) {
    return value >= 0.0f ? int(floor(value + 0.5f)) : int(ceil(value - 0.5f));
}

AetherTsdfSample aetherTsdfSample(uint threadIndex, device const uint4* candidateBlocks,
                                  device const float* depth, device const float* confidence,
                                  device const float4* color,
                                  constant AetherTsdfFrameUniforms& uniforms) {
    AetherTsdfSample result{};
    const uint voxelsPerBlock = uniforms.imageCandidates.w;
    const uint candidateIndex = threadIndex / voxelsPerBlock;
    if (candidateIndex >= uniforms.imageCandidates.z)
        return result;
    const uint blockResolution = uniforms.gridDimensionsBlock.w;
    uint local = threadIndex - candidateIndex * voxelsPerBlock;
    const uint localX = local % blockResolution;
    local /= blockResolution;
    const uint localY = local % blockResolution;
    const uint localZ = local / blockResolution;
    const uint3 global =
        candidateBlocks[candidateIndex].xyz * blockResolution + uint3(localX, localY, localZ);
    if (any(global >= uniforms.gridDimensionsBlock.xyz))
        return result;

    const float3 world = uniforms.originVoxelSize.xyz + float3(global) * uniforms.originVoxelSize.w;
    const float3 camera = aetherTsdfRotate(uniforms.worldToCameraQuaternion,
                                           world - uniforms.cameraTranslationDepthScale.xyz);
    if (!all(isfinite(camera)) || camera.z <= uniforms.truncationDepthWeight.y)
        return result;
    const float projectedX = uniforms.intrinsics.x * camera.x / camera.z + uniforms.intrinsics.z;
    const float projectedY = uniforms.intrinsics.y * camera.y / camera.z + uniforms.intrinsics.w;
    const int pixelX = aetherTsdfNearestPixel(projectedX);
    const int pixelY = aetherTsdfNearestPixel(projectedY);
    if (pixelX < 0 || pixelY < 0 || pixelX >= int(uniforms.imageCandidates.x) ||
        pixelY >= int(uniforms.imageCandidates.y))
        return result;
    const uint pixel = uint(pixelY) * uniforms.imageCandidates.x + uint(pixelX);
    const float observedDepth = depth[pixel] * uniforms.cameraTranslationDepthScale.w;
    if (!isfinite(observedDepth) || observedDepth < uniforms.truncationDepthWeight.y ||
        observedDepth > uniforms.truncationDepthWeight.z)
        return result;
    const float sampleConfidence = uniforms.confidence.z > 0.5f ? confidence[pixel] : 1.0f;
    if (!isfinite(sampleConfidence) || sampleConfidence < uniforms.confidence.y)
        return result;
    const float signedDistance = observedDepth - camera.z;
    if (signedDistance < -uniforms.truncationDepthWeight.x)
        return result;
    const float sampleWeight = sampleConfidence * uniforms.confidence.x;
    if (sampleWeight <= 0.0f)
        return result;
    result.accepted = true;
    result.normalizedDistance =
        clamp(signedDistance / uniforms.truncationDepthWeight.x, -1.0f, 1.0f);
    result.confidence = sampleWeight;
    result.color = color[pixel].xyz;
    return result;
}

kernel void aetherSparseTsdfClassify(device const uint4* candidateBlocks [[buffer(0)]],
                                     device const float* depth [[buffer(1)]],
                                     device const float* confidence [[buffer(2)]],
                                     device const float4* color [[buffer(3)]],
                                     device atomic_uint* updateCounts [[buffer(4)]],
                                     constant AetherTsdfFrameUniforms& uniforms [[buffer(5)]],
                                     uint threadIndex [[thread_position_in_grid]]) {
    const AetherTsdfSample sample =
        aetherTsdfSample(threadIndex, candidateBlocks, depth, confidence, color, uniforms);
    if (!sample.accepted)
        return;
    const uint candidate = threadIndex / uniforms.imageCandidates.w;
    atomic_fetch_add_explicit(&updateCounts[candidate], 1u, memory_order_relaxed);
}

kernel void aetherSparseTsdfInitialize(device AetherTsdfVoxelGpu* voxels [[buffer(0)]],
                                       constant uint& count [[buffer(1)]],
                                       uint index [[thread_position_in_grid]]) {
    if (index >= count)
        return;
    AetherTsdfVoxelGpu voxel{};
    voxel.distance = 1.0f;
    voxels[index] = voxel;
}

kernel void aetherSparseTsdfIntegrate(device const uint4* candidateBlocks [[buffer(0)]],
                                      device const float* depth [[buffer(1)]],
                                      device const float* confidence [[buffer(2)]],
                                      device const float4* color [[buffer(3)]],
                                      device AetherTsdfVoxelGpu* voxels [[buffer(4)]],
                                      device atomic_uint* newObservedCounts [[buffer(5)]],
                                      constant AetherTsdfFrameUniforms& uniforms [[buffer(6)]],
                                      uint threadIndex [[thread_position_in_grid]]) {
    const AetherTsdfSample sample =
        aetherTsdfSample(threadIndex, candidateBlocks, depth, confidence, color, uniforms);
    if (!sample.accepted)
        return;
    const uint candidate = threadIndex / uniforms.imageCandidates.w;
    AetherTsdfVoxelGpu voxel = voxels[threadIndex];
    if (voxel.weight <= 0.0f)
        atomic_fetch_add_explicit(&newObservedCounts[candidate], 1u, memory_order_relaxed);
    const float combinedWeight =
        min(uniforms.truncationDepthWeight.w, voxel.weight + sample.confidence);
    const float contribution = min(sample.confidence, combinedWeight);
    const float retained = combinedWeight - contribution;
    voxel.distance =
        (voxel.distance * retained + sample.normalizedDistance * contribution) / combinedWeight;
    const float3 integratedColor =
        (float3(voxel.colorRed, voxel.colorGreen, voxel.colorBlue) * retained +
         sample.color * contribution) /
        combinedWeight;
    voxel.colorRed = integratedColor.x;
    voxel.colorGreen = integratedColor.y;
    voxel.colorBlue = integratedColor.z;
    voxel.weight = combinedWeight;
    voxel.observations += 1u;
    voxels[threadIndex] = voxel;
}
