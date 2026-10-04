#include "shared/AetherShaderTypes.h"
#include <metal_stdlib>

using namespace metal;

struct ShadowVertexOutput {
    float4 position [[position]];
    float2 uv;
};

vertex ShadowVertexOutput aetherShadowVertex(uint vertexId [[vertex_id]],
                                 device const AetherMeshVertex* vertices [[buffer(0)]],
                                 constant AetherFrameUniforms& frame [[buffer(1)]],
                                 device const AetherJointMatrix* joints [[buffer(2)]],
                                 constant AetherSkinDraw& skin [[buffer(3)]],
                                 device const AetherMorphDelta* morphDeltas [[buffer(4)]],
                                 device const float* morphWeights [[buffer(5)]],
                                 constant AetherMorphDraw& morph [[buffer(6)]]) {
    const AetherMeshVertex meshVertex = vertices[vertexId];
    float4 position = float4(meshVertex.position, 1.0f);
    if (morph.enabled != 0u) {
        for (uint target = 0u; target < morph.targetCount; ++target) {
            const AetherMorphDelta delta = morphDeltas[target * morph.vertexCount + vertexId];
            position.xyz += delta.position.xyz * morphWeights[target];
        }
    }
    if (skin.enabled != 0u) {
        float4x4 skinMatrix = float4x4(0.0f);
        for (uint influence = 0u; influence < 4u; ++influence) {
            const uint joint = min(meshVertex.joints[influence], skin.jointCount - 1u);
            skinMatrix += joints[joint].position * meshVertex.weights[influence];
        }
        position = skinMatrix * position;
    }
    ShadowVertexOutput output;
    output.position = frame.viewProjection * frame.model * position;
    output.uv = meshVertex.textureCoordinate;
    return output;
}

fragment void aetherShadowFragment(ShadowVertexOutput input [[stage_in]],
                                   constant AetherMaterialUniforms& material [[buffer(2)]],
                                   texture2d<float> baseColorTexture [[texture(0)]],
                                   sampler baseColorSampler [[sampler(0)]]) {
    if (material.textureFlags.y != 1u)
        return;
    const float4 scaleOffset = material.uvScaleOffset[0];
    const float2 cosineSine = material.uvRotation[0].xy;
    const float2 scaled = input.uv * scaleOffset.xy;
    const float2 uv = float2(cosineSine.x * scaled.x - cosineSine.y * scaled.y,
                             cosineSine.y * scaled.x + cosineSine.x * scaled.y) + scaleOffset.zw;
    const float sampledAlpha = (material.textureFlags.x & 1u) != 0u
                                   ? baseColorTexture.sample(baseColorSampler, uv).a
                                   : 1.0f;
    const float alpha = material.baseColor.a * sampledAlpha;
    if (alpha < material.roughnessNormalOcclusionAlpha.w)
        discard_fragment();
}
