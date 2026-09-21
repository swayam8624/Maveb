#include "shared/AetherShaderTypes.h"
#include <metal_stdlib>

using namespace metal;

struct ViewportOutput {
    float4 position [[position]];
    float2 uv;
};

vertex ViewportOutput aetherViewportVertex(uint vertexId [[vertex_id]]) {
    constexpr AetherFloat2 positions[] = {{-1.0f, -1.0f}, {3.0f, -1.0f}, {-1.0f, 3.0f}};
    ViewportOutput output;
    output.position = float4(positions[vertexId], 0.0f, 1.0f);
    output.uv = positions[vertexId] * 0.5f + 0.5f;
    return output;
}

struct SceneBackgroundOutput {
    float4 color [[color(0)]];
    uint entityId [[color(1)]];
    float4 motion [[color(2)]];
    float depth [[depth(greater)]];
};

fragment SceneBackgroundOutput aetherSceneBackgroundFragment(
    ViewportOutput input [[stage_in]],
    constant AetherGaussianCompositionUniforms& composition [[buffer(0)]],
    texture2d<float> gaussianColor [[texture(0)]], texture2d<float> gaussianDepth [[texture(1)]],
    texture2d<uint> gaussianIds [[texture(2)]],
    texture2d<float> proxyNormalConfidence [[texture(3)]], depth2d<float> proxyDepth [[texture(4)]],
    texture2d<float> proxyMotion [[texture(6)]]) {
    const float3 background = float3(0.025f + input.uv.x * 0.02f);
    SceneBackgroundOutput output{float4(background, 1.0f), 0u, float4(0.0f), 0.0f};
    const uint2 dimensions(gaussianColor.get_width(), gaussianColor.get_height());
    const uint2 pixel = min(uint2(input.position.xy), dimensions - 1u);
    const bool hasProxy = composition.proxyParameters.x > 0.5f;
    const float proxyReverseDepth = hasProxy ? proxyDepth.read(pixel) : 0.0f;
    const float proxyConfidence =
        proxyReverseDepth > 0.0f ? proxyNormalConfidence.read(pixel).a : 0.0f;
    const bool proxySurface = proxyReverseDepth > 0.0f && proxyConfidence > 0.0f;
    if (composition.depthHistoryOpacity.y < 0.5f) {
        if (proxySurface) {
            output.depth = proxyReverseDepth;
            output.motion = proxyMotion.read(pixel);
        }
        return output;
    }

    const float4 gaussian = gaussianColor.read(pixel);
    const float linearDepth = gaussianDepth.read(pixel).r;
    if (!isfinite(linearDepth) || linearDepth <= 0.0f ||
        gaussian.a < composition.depthHistoryOpacity.w) {
        if (proxySurface) {
            output.depth = proxyReverseDepth;
            output.motion = proxyMotion.read(pixel);
        }
        return output;
    }

    const float gaussianReverseDepth =
        clamp(composition.depthHistoryOpacity.x / linearDepth, 0.0f, 1.0f);
    if (proxySurface) {
        const float proxyLinearDepth = composition.depthHistoryOpacity.x / proxyReverseDepth;
        const float tolerance =
            (composition.proxyParameters.y + composition.proxyParameters.z * proxyLinearDepth) *
            (1.0f + (1.0f - proxyConfidence) * composition.proxyParameters.w);
        if (linearDepth > proxyLinearDepth + tolerance) {
            output.depth = proxyReverseDepth;
            output.motion = proxyMotion.read(pixel);
            return output;
        }
    }

    output.color = float4(gaussian.rgb + (1.0f - gaussian.a) * background, 1.0f);
    output.entityId = gaussianIds.read(pixel).r;
    output.depth = gaussianReverseDepth;

    if (proxySurface && proxyReverseDepth > gaussianReverseDepth) {
        output.depth = proxyReverseDepth;
        output.motion = proxyMotion.read(pixel);
        // The visible color remains Gaussian, but proxy depth stabilizes shared occlusion.
        output.entityId = gaussianIds.read(pixel).r;
        return output;
    }

    const float2 currentUv = (float2(pixel) + 0.5f) / float2(dimensions);
    const float4 currentClip(float2(currentUv.x * 2.0f - 1.0f, 1.0f - currentUv.y * 2.0f),
                             output.depth, 1.0f);
    float4 world = composition.inverseCurrentViewProjection * currentClip;
    world /= world.w;
    const float4 previousClip = composition.previousViewProjection * world;
    if (composition.depthHistoryOpacity.z > 0.5f && previousClip.w > 0.0f) {
        const float3 previousNdc = previousClip.xyz / previousClip.w;
        const float2 previousUv(previousNdc.x * 0.5f + 0.5f, 0.5f - previousNdc.y * 0.5f);
        if (all(previousUv >= 0.0f) && all(previousUv <= 1.0f) && previousNdc.z >= 0.0f &&
            previousNdc.z <= 1.0f)
            output.motion = float4(currentUv - previousUv, previousNdc.z, 1.0f);
    }
    return output;
}

float3 acesPresentation(float3 color) {
    constexpr float a = 2.51f;
    constexpr float b = 0.03f;
    constexpr float c = 2.43f;
    constexpr float d = 0.59f;
    constexpr float e = 0.14f;
    return clamp((color * (a * color + b)) / (color * (c * color + d) + e), 0.0f, 1.0f);
}

fragment float4 aetherViewportFragment(ViewportOutput input [[stage_in]],
                                       constant AetherPresentationUniforms& presentation
                                       [[buffer(0)]],
                                       texture2d<float> sourceColor [[texture(0)]],
                                       texture2d<float> bloomHalf [[texture(1)]],
                                       texture2d<float> bloomQuarter [[texture(2)]],
                                       depth2d_array<float> directionalShadows [[texture(3)]],
                                       depth2d_array<float> localShadows [[texture(4)]],
                                       sampler linearSampler [[sampler(0)]]) {
    const float3 background = float3(0.025f + input.uv.x * 0.02f);
    if (presentation.mode == 0u)
        return float4(background, 1.0f);
    const uint2 pixel = uint2(input.position.xy);
    if (presentation.mode == 3u) {
        const uint2 dimensions(directionalShadows.get_width(), directionalShadows.get_height());
        const uint2 shadowPixel = min(uint2(input.uv * float2(dimensions)), dimensions - 1u);
        const float depth = directionalShadows.read(shadowPixel, presentation.padding1);
        return float4(float3(depth), 1.0f);
    }
    if (presentation.mode == 4u) {
        const uint2 dimensions(localShadows.get_width(), localShadows.get_height());
        const uint2 shadowPixel = min(uint2(input.uv * float2(dimensions)), dimensions - 1u);
        const float depth = localShadows.read(shadowPixel, presentation.padding1);
        return float4(float3(depth), 1.0f);
    }
    const float4 source = sourceColor.read(pixel);
    if (presentation.mode == 2u) {
        const float2 uv =
            (float2(pixel) + 0.5f) / float2(sourceColor.get_width(), sourceColor.get_height());
        const float3 bloom =
            bloomHalf.sample(linearSampler, uv).rgb + bloomQuarter.sample(linearSampler, uv).rgb;
        const float3 hdr = max(source.rgb + bloom * presentation.bloomIntensity, 0.0f);
        return float4(acesPresentation(hdr * exp2(presentation.exposureStops)), 1.0f);
    }
    const float4 gaussian = source;
    const float3 composite = gaussian.rgb + (1.0f - gaussian.a) * float3(background);
    return float4(composite, 1.0f);
}

fragment float4 aetherBloomDownsampleFragment(ViewportOutput input [[stage_in]],
                                              constant AetherBloomUniforms& bloom [[buffer(0)]],
                                              texture2d<float> source [[texture(0)]],
                                              sampler linearSampler [[sampler(0)]]) {
    const float2 uv = input.position.xy * bloom.inverseSourceSize * 2.0f;
    const float2 texel = bloom.inverseSourceSize;
    float3 color = source.sample(linearSampler, uv).rgb * 0.25f;
    color += source.sample(linearSampler, uv + float2(texel.x, 0.0f)).rgb * 0.125f;
    color += source.sample(linearSampler, uv - float2(texel.x, 0.0f)).rgb * 0.125f;
    color += source.sample(linearSampler, uv + float2(0.0f, texel.y)).rgb * 0.125f;
    color += source.sample(linearSampler, uv - float2(0.0f, texel.y)).rgb * 0.125f;
    color += source.sample(linearSampler, uv + texel).rgb * 0.0625f;
    color += source.sample(linearSampler, uv - texel).rgb * 0.0625f;
    color += source.sample(linearSampler, uv + float2(texel.x, -texel.y)).rgb * 0.0625f;
    color += source.sample(linearSampler, uv + float2(-texel.x, texel.y)).rgb * 0.0625f;
    if (bloom.threshold > 0.0f) {
        const float brightness = max(color.r, max(color.g, color.b));
        const float soft =
            clamp(brightness - bloom.threshold + bloom.knee, 0.0f, 2.0f * bloom.knee);
        const float contribution =
            max(brightness - bloom.threshold, soft * soft / max(4.0f * bloom.knee, 1.0e-5f));
        color *= contribution / max(brightness, 1.0e-5f);
    }
    return float4(max(color, 0.0f), 1.0f);
}

struct TemporalOutput {
    float4 color [[color(0)]];
    float depth [[color(1)]];
};

fragment TemporalOutput aetherTemporalResolveFragment(
    ViewportOutput input [[stage_in]], constant AetherTemporalUniforms& temporal [[buffer(0)]],
    texture2d<float> currentColor [[texture(0)]], depth2d<float> currentDepth [[texture(1)]],
    texture2d<float> historyColor [[texture(2)]], texture2d<float> historyDepth [[texture(3)]],
    texture2d<float> currentMotion [[texture(4)]], sampler historySampler [[sampler(0)]]) {
    const uint2 dimensions(currentColor.get_width(), currentColor.get_height());
    const uint2 pixel = min(uint2(input.position.xy), dimensions - 1u);
    const float4 current = currentColor.read(pixel);
    const float depth = currentDepth.read(pixel);
    TemporalOutput output{current, depth};
    if (temporal.historyParameters.x < 0.5f || depth <= 0.0f)
        return output;

    const float2 uv = (float2(pixel) + 0.5f) / float2(dimensions);
    if (temporal.historyParameters.w > 0.5f &&
        all(uv >= temporal.invalidationRect.xy) &&
        all(uv <= temporal.invalidationRect.zw))
        return output;

    const float4 motion = currentMotion.read(pixel);
    if (motion.w < 0.5f)
        return output;
    const float2 previousUv = uv - motion.xy;
    if (any(previousUv < 0.0f) || any(previousUv > 1.0f))
        return output;
    const float priorDepth = historyDepth.sample(historySampler, previousUv).r;
    if (abs(priorDepth - motion.z) > temporal.historyParameters.z)
        return output;

    float3 neighborhoodMinimum = current.rgb;
    float3 neighborhoodMaximum = current.rgb;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            const int2 coordinate = clamp(int2(pixel) + int2(x, y), int2(0), int2(dimensions) - 1);
            const float3 value = currentColor.read(uint2(coordinate)).rgb;
            neighborhoodMinimum = min(neighborhoodMinimum, value);
            neighborhoodMaximum = max(neighborhoodMaximum, value);
        }
    }
    const float3 history = clamp(historyColor.sample(historySampler, previousUv).rgb,
                                 neighborhoodMinimum, neighborhoodMaximum);
    output.color.rgb = mix(current.rgb, history, temporal.historyParameters.y);
    return output;
}
