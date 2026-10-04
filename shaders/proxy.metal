#include "shared/AetherShaderTypes.h"
#include <metal_stdlib>

using namespace metal;

struct ProxyRasterOutput {
    float4 position [[position]];
    float3 normal;
    float confidence;
    float4 currentClip;
    float4 previousClip;
};

vertex ProxyRasterOutput aetherProxyVertex(uint vertexId [[vertex_id]],
                                           device const AetherProxyGpuVertex* vertices
                                           [[buffer(0)]],
                                           constant AetherProxyUniforms& uniforms [[buffer(1)]]) {
    const AetherProxyGpuVertex source = vertices[vertexId];
    const float4 worldPosition(source.positionConfidence.xyz, 1.0f);
    ProxyRasterOutput output;
    output.currentClip = uniforms.viewProjection * worldPosition;
    output.previousClip = uniforms.previousViewProjection * worldPosition;
    output.position = output.currentClip;
    output.normal = source.normalPadding.xyz;
    output.confidence = source.positionConfidence.w;
    return output;
}

struct ProxyGBufferOutput {
    // Encoded world normal in rgb and reconstruction confidence in alpha.
    float4 normalConfidence [[color(0)]];
    uint proxyId [[color(1)]];
    // Current-minus-previous UV, previous reverse-Z depth, validity.
    float4 motion [[color(2)]];
};

fragment ProxyGBufferOutput aetherProxyFragment(ProxyRasterOutput input [[stage_in]],
                                                constant AetherProxyUniforms& uniforms
                                                [[buffer(1)]]) {
    ProxyGBufferOutput output;
    const float3 normal = normalize(input.normal);
    output.normalConfidence = float4(normal * 0.5f + 0.5f, clamp(input.confidence, 0.0f, 1.0f));
    output.proxyId = 1u;
    output.motion = float4(0.0f);
    if (uniforms.options.x > 0.5f && input.currentClip.w > 0.0f && input.previousClip.w > 0.0f) {
        const float3 currentNdc = input.currentClip.xyz / input.currentClip.w;
        const float3 previousNdc = input.previousClip.xyz / input.previousClip.w;
        const float2 currentUv(currentNdc.x * 0.5f + 0.5f, 0.5f - currentNdc.y * 0.5f);
        const float2 previousUv(previousNdc.x * 0.5f + 0.5f, 0.5f - previousNdc.y * 0.5f);
        if (all(previousUv >= 0.0f) && all(previousUv <= 1.0f) && previousNdc.z >= 0.0f &&
            previousNdc.z <= 1.0f)
            output.motion = float4(currentUv - previousUv, previousNdc.z, 1.0f);
    }
    return output;
}
