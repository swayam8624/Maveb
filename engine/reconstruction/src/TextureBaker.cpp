#include <aether/reconstruction/TextureBaker.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numeric>
#include <optional>
#include <span>
#include <utility>

namespace aether::reconstruction {
namespace {

constexpr float epsilon = 1.0e-8F;

struct PreparedCamera final {
    const TextureBakeCamera* source{};
    simd_float4x4 worldToCamera{};
    simd_float3 position{};
    std::vector<float> depth;
    float exposureGain{1.0F};
};

struct Candidate final {
    std::size_t camera{};
    float score{};
};

struct VisibilityQuery final {
    std::size_t width{};
    std::size_t height{};
    float tolerance{};
};

bool finite(simd_float3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}
bool finite(simd_float4 value) {
    return finite(value.xyz) && std::isfinite(value.w);
}
bool finite(simd_float4x4 value) {
    return finite(value.columns[0]) && finite(value.columns[1]) && finite(value.columns[2]) &&
           finite(value.columns[3]);
}

simd_float3 transformPoint(simd_float4x4 transform, simd_float3 point) {
    return simd_mul(transform, simd_make_float4(point, 1.0F)).xyz;
}

std::optional<simd_float3> project(const PreparedCamera& camera, simd_float3 world) {
    const auto local = transformPoint(camera.worldToCamera, world);
    if (!finite(local) || local.z <= epsilon)
        return std::nullopt;
    const float x = local.x / local.z;
    const float y = local.y / local.z;
    const float radius2 = x * x + y * y;
    const float radial = 1.0F + camera.source->k1 * radius2 +
                         camera.source->k2 * radius2 * radius2 +
                         camera.source->k3 * radius2 * radius2 * radius2;
    float distortedX = x * radial;
    float distortedY = y * radial;
    if (camera.source->model == TextureCameraModel::opencv) {
        distortedX +=
            2.0F * camera.source->p1 * x * y + camera.source->p2 * (radius2 + 2.0F * x * x);
        distortedY +=
            camera.source->p1 * (radius2 + 2.0F * y * y) + 2.0F * camera.source->p2 * x * y;
    }
    return simd_float3{camera.source->focalX * distortedX + camera.source->principalX,
                       camera.source->focalY * distortedY + camera.source->principalY, local.z};
}

float edge(simd_float2 a, simd_float2 b, simd_float2 point) {
    return (point.x - a.x) * (b.y - a.y) - (point.y - a.y) * (b.x - a.x);
}

void rasterizeDepth(PreparedCamera& camera, std::span<const mesh::MeshVertex> vertices,
                    std::span<const std::uint32_t> indices, std::size_t width, std::size_t height) {
    camera.depth.assign(width * height, std::numeric_limits<float>::infinity());
    const float scaleX = static_cast<float>(width) / static_cast<float>(camera.source->image.width);
    const float scaleY =
        static_cast<float>(height) / static_cast<float>(camera.source->image.height);
    for (std::size_t triangle = 0; triangle < indices.size(); triangle += 3) {
        std::array<simd_float3, 3> projected;
        bool valid = true;
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const auto value = project(camera, vertices[indices[triangle + corner]].position);
            if (!value) {
                valid = false;
                break;
            }
            projected[corner] = {value->x * scaleX, value->y * scaleY, value->z};
        }
        if (!valid)
            continue;
        const std::array<simd_float2, 3> points{
            {projected[0].xy, projected[1].xy, projected[2].xy}};
        const float area = edge(points[0], points[1], points[2]);
        if (std::abs(area) <= epsilon)
            continue;
        const int minimumX = std::max(
            0, static_cast<int>(std::floor(std::min({points[0].x, points[1].x, points[2].x}))));
        const int maximumX = std::min(
            static_cast<int>(width) - 1,
            static_cast<int>(std::ceil(std::max({points[0].x, points[1].x, points[2].x}))));
        const int minimumY = std::max(
            0, static_cast<int>(std::floor(std::min({points[0].y, points[1].y, points[2].y}))));
        const int maximumY = std::min(
            static_cast<int>(height) - 1,
            static_cast<int>(std::ceil(std::max({points[0].y, points[1].y, points[2].y}))));
        for (int y = minimumY; y <= maximumY; ++y) {
            for (int x = minimumX; x <= maximumX; ++x) {
                const simd_float2 sample{static_cast<float>(x) + 0.5F,
                                         static_cast<float>(y) + 0.5F};
                const float first = edge(points[1], points[2], sample) / area;
                const float second = edge(points[2], points[0], sample) / area;
                const float third = 1.0F - first - second;
                if (first < 0.0F || second < 0.0F || third < 0.0F)
                    continue;
                const float reciprocalDepth =
                    first / projected[0].z + second / projected[1].z + third / projected[2].z;
                if (reciprocalDepth <= epsilon)
                    continue;
                const float depth = 1.0F / reciprocalDepth;
                auto& current =
                    camera.depth[static_cast<std::size_t>(y) * width + static_cast<std::size_t>(x)];
                current = std::min(current, depth);
            }
        }
    }
}

bool visible(const PreparedCamera& camera, simd_float3 projected, const VisibilityQuery& query) {
    if (projected.x < 0.0F || projected.y < 0.0F ||
        projected.x >= static_cast<float>(camera.source->image.width) ||
        projected.y >= static_cast<float>(camera.source->image.height))
        return false;
    const auto x = std::min(
        query.width - 1, static_cast<std::size_t>(projected.x * static_cast<float>(query.width) /
                                                  static_cast<float>(camera.source->image.width)));
    const auto y =
        std::min(query.height - 1,
                 static_cast<std::size_t>(projected.y * static_cast<float>(query.height) /
                                          static_cast<float>(camera.source->image.height)));
    float oracle = std::numeric_limits<float>::infinity();
    const auto minimumX = x == 0 ? 0 : x - 1;
    const auto minimumY = y == 0 ? 0 : y - 1;
    for (std::size_t sampleY = minimumY; sampleY <= std::min(query.height - 1, y + 1); ++sampleY)
        for (std::size_t sampleX = minimumX; sampleX <= std::min(query.width - 1, x + 1); ++sampleX)
            oracle = std::min(oracle, camera.depth[sampleY * query.width + sampleX]);
    return std::isfinite(oracle) && projected.z <= oracle * (1.0F + query.tolerance) + 1.0e-4F;
}

simd_float3 sampleBilinear(const TextureBakeImage& image, simd_float2 point) {
    const float x = std::clamp(point.x - 0.5F, 0.0F, static_cast<float>(image.width - 1));
    const float y = std::clamp(point.y - 0.5F, 0.0F, static_cast<float>(image.height - 1));
    const auto x0 = static_cast<std::size_t>(std::floor(x));
    const auto y0 = static_cast<std::size_t>(std::floor(y));
    const auto x1 = std::min(x0 + 1, image.width - 1);
    const auto y1 = std::min(y0 + 1, image.height - 1);
    const float tx = x - static_cast<float>(x0);
    const float ty = y - static_cast<float>(y0);
    return simd_mix(
        simd_mix(image.pixels[y0 * image.width + x0], image.pixels[y0 * image.width + x1], tx),
        simd_mix(image.pixels[y1 * image.width + x0], image.pixels[y1 * image.width + x1], tx), ty);
}

float luminance(simd_float3 color) {
    return std::max(1.0e-5F, simd_dot(color, simd_float3{0.2126F, 0.7152F, 0.0722F}));
}

float median(std::vector<float> values) {
    if (values.empty())
        return 1.0F;
    const auto middle = values.begin() + static_cast<std::ptrdiff_t>(values.size() / 2);
    std::nth_element(values.begin(), middle, values.end());
    return *middle;
}

} // namespace

Result<TextureBakeResult> TextureBaker::bake(const mesh::MeshPrimitive& source,
                                             const std::vector<TextureBakeCamera>& cameras,
                                             const TextureBakeConfig& config) {
    const std::size_t triangleCount = source.indices.size() / 3;
    if (source.vertices.empty() || source.indices.empty() || source.indices.size() % 3 != 0 ||
        triangleCount > config.maximumTriangles)
        return fail(ErrorCode::invalidArgument, "Texture baking requires a bounded triangle mesh");
    if (cameras.empty() || cameras.size() > config.maximumCameras)
        return fail(ErrorCode::invalidArgument, "Texture baking requires calibrated cameras");
    if (config.atlasSize == 0 || config.atlasSize > 8192 ||
        config.atlasSize > config.maximumAtlasPixels / config.atlasSize ||
        config.visibilityWidth == 0 || config.visibilityHeight == 0 ||
        config.maximumCamerasPerTriangle == 0 || config.maximumCameras == 0 ||
        config.maximumSourcePixels == 0 || config.gutterPixels > config.atlasSize / 4 ||
        !std::isfinite(config.minimumFacingCosine) || config.minimumFacingCosine < 0.0F ||
        config.minimumFacingCosine >= 1.0F || !std::isfinite(config.relativeDepthTolerance) ||
        config.relativeDepthTolerance < 0.0F || !std::isfinite(config.maximumExposureGain) ||
        config.maximumExposureGain < 1.0F)
        return fail(ErrorCode::invalidArgument, "Texture bake configuration is invalid");
    for (std::size_t offset = 0; offset < source.indices.size(); offset += 3) {
        const auto a = source.indices[offset];
        const auto b = source.indices[offset + 1];
        const auto c = source.indices[offset + 2];
        if (a >= source.vertices.size() || b >= source.vertices.size() ||
            c >= source.vertices.size() || a == b || b == c || a == c)
            return fail(ErrorCode::corruptData, "Texture source contains invalid indices");
        if (!finite(source.vertices[a].position) || !finite(source.vertices[b].position) ||
            !finite(source.vertices[c].position) ||
            simd_length_squared(
                simd_cross(source.vertices[b].position - source.vertices[a].position,
                           source.vertices[c].position - source.vertices[a].position)) <= epsilon)
            return fail(ErrorCode::corruptData, "Texture source contains invalid geometry");
    }

    std::size_t totalSourcePixels{};
    std::vector<PreparedCamera> prepared;
    prepared.reserve(cameras.size());
    for (const auto& camera : cameras) {
        if (camera.image.width < 2 || camera.image.height < 2 ||
            camera.image.pixels.size() != camera.image.width * camera.image.height ||
            camera.focalX <= 0.0F || camera.focalY <= 0.0F || !std::isfinite(camera.focalX) ||
            !std::isfinite(camera.focalY) || !std::isfinite(camera.principalX) ||
            !std::isfinite(camera.principalY) || !std::isfinite(camera.k1) ||
            !std::isfinite(camera.k2) || !std::isfinite(camera.k3) || !std::isfinite(camera.p1) ||
            !std::isfinite(camera.p2) || !finite(camera.cameraToWorld) ||
            std::ranges::any_of(
                camera.image.pixels,
                [](simd_float3 color) {
                    return !finite(color) || simd_any(color < simd_float3{});
                }))
            return fail(ErrorCode::corruptData, "Texture camera calibration or image is invalid",
                        camera.imageName);
        const auto cameraPixels = camera.image.width * camera.image.height;
        if (cameraPixels > config.maximumSourcePixels - totalSourcePixels)
            return fail(ErrorCode::resourceExhausted,
                        "Decoded texture images exceed the configured pixel budget");
        totalSourcePixels += cameraPixels;
        const float determinant = simd_determinant(camera.cameraToWorld);
        if (!std::isfinite(determinant) || std::abs(determinant) <= epsilon)
            return fail(ErrorCode::corruptData, "Texture camera transform is singular",
                        camera.imageName);
        PreparedCamera value{&camera,
                             simd_inverse(camera.cameraToWorld),
                             camera.cameraToWorld.columns[3].xyz,
                             {},
                             1.0F};
        rasterizeDepth(value, source.vertices, source.indices, config.visibilityWidth,
                       config.visibilityHeight);
        prepared.push_back(std::move(value));
    }

    std::vector<std::vector<Candidate>> candidates(triangleCount);
    std::vector<std::vector<float>> exposureSamples(cameras.size());
    const VisibilityQuery visibility{config.visibilityWidth, config.visibilityHeight,
                                     config.relativeDepthTolerance};
    for (std::size_t triangle = 0; triangle < triangleCount; ++triangle) {
        const auto a = source.vertices[source.indices[triangle * 3]].position;
        const auto b = source.vertices[source.indices[triangle * 3 + 1]].position;
        const auto c = source.vertices[source.indices[triangle * 3 + 2]].position;
        const auto centroid = (a + b + c) / 3.0F;
        const auto normal = simd_normalize(simd_cross(b - a, c - a));
        for (std::size_t cameraIndex = 0; cameraIndex < prepared.size(); ++cameraIndex) {
            auto projected = project(prepared[cameraIndex], centroid);
            const auto direction = simd_normalize(prepared[cameraIndex].position - centroid);
            const float facing = std::abs(simd_dot(normal, direction));
            if (!projected || facing < config.minimumFacingCosine ||
                !visible(prepared[cameraIndex], *projected, visibility))
                continue;
            const float borderX =
                std::min(projected->x,
                         static_cast<float>(cameras[cameraIndex].image.width) - projected->x) /
                static_cast<float>(cameras[cameraIndex].image.width);
            const float borderY =
                std::min(projected->y,
                         static_cast<float>(cameras[cameraIndex].image.height) - projected->y) /
                static_cast<float>(cameras[cameraIndex].image.height);
            const float score = facing *
                                std::clamp(std::min(borderX, borderY) * 8.0F, 0.05F, 1.0F) /
                                std::max(projected->z * projected->z, 1.0e-4F);
            candidates[triangle].push_back({cameraIndex, score});
            exposureSamples[cameraIndex].push_back(
                std::log(luminance(sampleBilinear(cameras[cameraIndex].image, projected->xy))));
        }
        std::ranges::sort(candidates[triangle], [](const Candidate& left, const Candidate& right) {
            return left.score > right.score ||
                   (left.score == right.score && left.camera < right.camera);
        });
        if (candidates[triangle].size() > config.maximumCamerasPerTriangle)
            candidates[triangle].resize(config.maximumCamerasPerTriangle);
    }
    std::vector<float> cameraMedians;
    for (auto& samples : exposureSamples)
        if (!samples.empty())
            cameraMedians.push_back(median(samples));
    const float targetLogLuminance = median(cameraMedians);
    for (std::size_t index = 0; index < prepared.size(); ++index) {
        if (!exposureSamples[index].empty())
            prepared[index].exposureGain =
                std::clamp(std::exp(targetLogLuminance - median(exposureSamples[index])),
                           1.0F / config.maximumExposureGain, config.maximumExposureGain);
    }

    const auto columns =
        static_cast<std::size_t>(std::ceil(std::sqrt(static_cast<double>(triangleCount))));
    const auto rows = (triangleCount + columns - 1) / columns;
    const auto cell = std::min(config.atlasSize / columns, config.atlasSize / rows);
    if (cell <= config.gutterPixels * 2 + 1)
        return fail(ErrorCode::resourceExhausted,
                    "Texture atlas cannot allocate every triangle with gutters");
    const auto inner = cell - config.gutterPixels * 2;
    TextureBakeResult result;
    result.atlasWidth = config.atlasSize;
    result.atlasHeight = config.atlasSize;
    result.atlasPixels.assign(config.atlasSize * config.atlasSize,
                              simd_float3{0.18F, 0.18F, 0.18F});
    result.coverageMask.assign(result.atlasPixels.size(), 0);
    result.primitive.name = source.name.empty() ? "Maveb textured mesh" : source.name;
    result.primitive.vertices.reserve(triangleCount * 3);
    result.primitive.indices.reserve(triangleCount * 3);
    for (std::size_t triangle = 0; triangle < triangleCount; ++triangle) {
        const auto tileX = (triangle % columns) * cell + config.gutterPixels;
        const auto tileY = (triangle / columns) * cell + config.gutterPixels;
        std::array<mesh::MeshVertex, 3> vertices{source.vertices[source.indices[triangle * 3]],
                                                 source.vertices[source.indices[triangle * 3 + 1]],
                                                 source.vertices[source.indices[triangle * 3 + 2]]};
        const auto geometricNormal =
            simd_normalize(simd_cross(vertices[1].position - vertices[0].position,
                                      vertices[2].position - vertices[0].position));
        const auto tangent = simd_normalize(vertices[1].position - vertices[0].position);
        const std::array<simd_float2, 3> uv{
            {{static_cast<float>(tileX) / static_cast<float>(config.atlasSize),
              static_cast<float>(tileY) / static_cast<float>(config.atlasSize)},
             {static_cast<float>(tileX + inner - 1) / static_cast<float>(config.atlasSize),
              static_cast<float>(tileY) / static_cast<float>(config.atlasSize)},
             {static_cast<float>(tileX) / static_cast<float>(config.atlasSize),
              static_cast<float>(tileY + inner - 1) / static_cast<float>(config.atlasSize)}}};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            vertices[corner].normal = geometricNormal;
            vertices[corner].tangent = simd_float4{tangent.x, tangent.y, tangent.z, 1.0F};
            vertices[corner].textureCoordinate = uv[corner];
            result.primitive.indices.push_back(
                static_cast<std::uint32_t>(result.primitive.vertices.size()));
            result.primitive.vertices.push_back(vertices[corner]);
        }
        for (std::size_t y = 0; y < inner; ++y) {
            for (std::size_t x = 0; x + y < inner; ++x) {
                const float second = (static_cast<float>(x) + 0.5F) / static_cast<float>(inner);
                const float third = (static_cast<float>(y) + 0.5F) / static_cast<float>(inner);
                const float first = 1.0F - second - third;
                const auto world = first * vertices[0].position + second * vertices[1].position +
                                   third * vertices[2].position;
                simd_float3 accumulated{};
                float totalWeight{};
                for (const auto candidate : candidates[triangle]) {
                    auto projected = project(prepared[candidate.camera], world);
                    if (!projected ||
                        !visible(prepared[candidate.camera], *projected, visibility)) {
                        ++result.report.visibilityRejectedSamples;
                        continue;
                    }
                    accumulated += sampleBilinear(cameras[candidate.camera].image, projected->xy) *
                                   prepared[candidate.camera].exposureGain * candidate.score;
                    totalWeight += candidate.score;
                }
                const auto atlasIndex = (tileY + y) * config.atlasSize + tileX + x;
                if (totalWeight > 0.0F) {
                    result.atlasPixels[atlasIndex] =
                        simd_clamp(accumulated / totalWeight, 0.0F, 1.0F);
                    result.coverageMask[atlasIndex] = 1;
                    ++result.report.texturedTexels;
                } else {
                    ++result.report.unobservedTexels;
                }
            }
        }
    }
    if (result.report.texturedTexels == 0)
        return fail(ErrorCode::corruptData, "No mesh surface is visible in the supplied cameras");
    for (std::size_t iteration = 0; iteration < config.gutterPixels; ++iteration) {
        auto pixels = result.atlasPixels;
        auto mask = result.coverageMask;
        for (std::size_t y = 1; y + 1 < config.atlasSize; ++y)
            for (std::size_t x = 1; x + 1 < config.atlasSize; ++x) {
                const auto index = y * config.atlasSize + x;
                if (result.coverageMask[index])
                    continue;
                simd_float3 sum{};
                float count{};
                for (const auto offset : std::array<std::ptrdiff_t, 4>{
                         -1, 1, -static_cast<std::ptrdiff_t>(config.atlasSize),
                         static_cast<std::ptrdiff_t>(config.atlasSize)}) {
                    const auto neighbor =
                        static_cast<std::size_t>(static_cast<std::ptrdiff_t>(index) + offset);
                    if (result.coverageMask[neighbor]) {
                        sum += result.atlasPixels[neighbor];
                        count += 1.0F;
                    }
                }
                if (count > 0.0F) {
                    pixels[index] = sum / count;
                    mask[index] = 2;
                }
            }
        result.atlasPixels = std::move(pixels);
        result.coverageMask = std::move(mask);
    }
    result.report.triangles = triangleCount;
    result.report.cameras = cameras.size();
    result.report.coverage =
        static_cast<float>(result.report.texturedTexels) /
        static_cast<float>(result.report.texturedTexels + result.report.unobservedTexels);
    result.report.exposureGains.reserve(prepared.size());
    for (const auto& camera : prepared)
        result.report.exposureGains.push_back(camera.exposureGain);
    return result;
}

} // namespace aether::reconstruction
