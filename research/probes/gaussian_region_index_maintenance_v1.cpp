// Incremental-maintenance companion to gaussian_region_index_v0.cpp.
// Synthetic only. Tests whether a persistent RegionKey -> Gaussian bucket index
// can be updated in proportion to primitives that cross cells instead of rebuilt.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <unordered_map>
#include <vector>

struct Key {
    int x{}, y{}, z{};
    bool operator==(const Key& o) const noexcept {
        return x == o.x && y == o.y && z == o.z;
    }
};
struct Hash {
    std::size_t operator()(const Key& k) const noexcept {
        std::uint64_t h = 1469598103934665603ULL;
        for (int v : {k.x, k.y, k.z}) {
            h ^= static_cast<std::uint32_t>(v);
            h *= 1099511628211ULL;
        }
        return static_cast<std::size_t>(h);
    }
};
struct Point {
    float x{}, y{}, z{};
};
static Key regionKey(const Point& p, float cell = 0.5F) {
    return {static_cast<int>(std::floor(p.x / cell)), static_cast<int>(std::floor(p.y / cell)),
            static_cast<int>(std::floor(p.z / cell))};
}
template <class Fn> double milliseconds(Fn&& fn) {
    const auto a = std::chrono::steady_clock::now();
    fn();
    const auto b = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(b - a).count();
}
using Buckets = std::unordered_map<Key, std::vector<std::uint32_t>, Hash>;
static Buckets build(const std::vector<Point>& points) {
    Buckets buckets;
    buckets.reserve(points.size() / 2);
    for (std::uint32_t i = 0; i < points.size(); ++i)
        buckets[regionKey(points[i])].push_back(i);
    return buckets;
}
static void eraseOne(std::vector<std::uint32_t>& values, std::uint32_t id) {
    const auto found = std::find(values.begin(), values.end(), id);
    if (found != values.end()) {
        *found = values.back();
        values.pop_back();
    }
}
int main() {
    std::mt19937_64 rng(7);
    std::uniform_real_distribution<float> position(-25.0F, 25.0F), delta(-0.9F, 0.9F);
    std::cout << "N,move_frac,moved,rebuild_ms,maintain_ms,equal\n";
    for (std::size_t count : {100'000ULL, 250'000ULL, 500'000ULL, 1'000'000ULL}) {
        std::vector<Point> base(count);
        for (auto& p : base)
            p = {position(rng), position(rng), position(rng)};
        const Buckets baseline = build(base);
        for (double fraction : {0.001, 0.0025, 0.005, 0.01, 0.02, 0.05, 0.10, 0.25}) {
            auto points = base;
            auto maintained = baseline;
            const std::size_t moved =
                std::max<std::size_t>(1, static_cast<std::size_t>(count * fraction));
            std::vector<std::pair<Key, Key>> moves;
            moves.reserve(moved);
            for (std::uint32_t id = 0; id < moved; ++id) {
                const Key oldKey = regionKey(points[id]);
                points[id].x += delta(rng);
                points[id].y += delta(rng);
                points[id].z += delta(rng);
                moves.emplace_back(oldKey, regionKey(points[id]));
            }
            Buckets rebuilt;
            const double rebuildMs = milliseconds([&] { rebuilt = build(points); });
            const double maintainMs = milliseconds([&] {
                for (std::uint32_t id = 0; id < moved; ++id) {
                    const auto [oldKey, newKey] = moves[id];
                    if (oldKey == newKey)
                        continue;
                    auto old = maintained.find(oldKey);
                    if (old != maintained.end()) {
                        eraseOne(old->second, id);
                        if (old->second.empty())
                            maintained.erase(old);
                    }
                    maintained[newKey].push_back(id);
                }
            });
            bool equal = maintained.size() == rebuilt.size();
            if (equal) {
                for (const auto& [key, expected] : rebuilt) {
                    const auto found = maintained.find(key);
                    if (found == maintained.end()) {
                        equal = false;
                        break;
                    }
                    auto lhs = expected, rhs = found->second;
                    std::sort(lhs.begin(), lhs.end());
                    std::sort(rhs.begin(), rhs.end());
                    if (lhs != rhs) {
                        equal = false;
                        break;
                    }
                }
            }
            std::cout << count << ',' << fraction << ',' << moved << ',' << rebuildMs << ','
                      << maintainMs << ',' << (equal ? 1 : 0) << '\n';
        }
    }
}
