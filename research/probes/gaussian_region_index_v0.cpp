// Synthetic falsification probe for Gaussian region indexing.
// Not production MAVEB code and not a paper benchmark.
// It compares PR #28-style full Gaussian scans against a persistent
// RegionKey -> Gaussian-index lookup under identical cell semantics.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <random>
#include <unordered_map>
#include <unordered_set>
#include <vector>

struct Key {
    int x{}, y{}, z{};
    bool operator==(const Key& o) const noexcept { return x == o.x && y == o.y && z == o.z; }
};
struct Hash {
    std::size_t operator()(const Key& k) const noexcept {
        std::uint64_t h = 1469598103934665603ULL;
        for (int value : {k.x, k.y, k.z}) {
            h ^= static_cast<std::uint32_t>(value);
            h *= 1099511628211ULL;
        }
        return static_cast<std::size_t>(h);
    }
};
struct Point { float x{}, y{}, z{}; };

static Key regionKey(const Point& p, float cell) {
    return {static_cast<int>(std::floor(p.x / cell)),
            static_cast<int>(std::floor(p.y / cell)),
            static_cast<int>(std::floor(p.z / cell))};
}

template <class Fn>
double milliseconds(Fn&& fn) {
    const auto start = std::chrono::steady_clock::now();
    fn();
    const auto end = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(end - start).count();
}

int main() {
    std::mt19937_64 rng(42);
    std::uniform_real_distribution<float> uniform(-25.0F, 25.0F);
    constexpr float cellSize = 0.5F;

    std::cout << "N,dirty_frac,occupied_cells,dirty_cells,selected,scan_inspections,"
                 "index_inspections,build_ms,scan_ms,index_ms,equal\n";

    for (std::size_t count : {10'000ULL, 50'000ULL, 100'000ULL, 250'000ULL,
                              500'000ULL, 1'000'000ULL}) {
        std::vector<Point> points(count);
        for (auto& point : points)
            point = {uniform(rng), uniform(rng), uniform(rng)};

        std::unordered_map<Key, std::vector<std::uint32_t>, Hash> index;
        index.reserve(count / 2);
        const double buildMs = milliseconds([&] {
            for (std::uint32_t i = 0; i < points.size(); ++i)
                index[regionKey(points[i], cellSize)].push_back(i);
        });

        std::vector<Key> occupied;
        occupied.reserve(index.size());
        for (const auto& [key, indices] : index) {
            static_cast<void>(indices);
            occupied.push_back(key);
        }
        std::shuffle(occupied.begin(), occupied.end(), rng);

        for (double fraction : {0.01, 0.02, 0.05, 0.10, 0.25, 0.50}) {
            std::size_t dirtyCount =
                std::max<std::size_t>(1, static_cast<std::size_t>(std::ceil(index.size() * fraction)));
            dirtyCount = std::min(dirtyCount, index.size());

            std::unordered_set<Key, Hash> dirty;
            dirty.reserve(dirtyCount * 2);
            for (std::size_t i = 0; i < dirtyCount; ++i)
                dirty.insert(occupied[i]);

            std::vector<std::uint32_t> scanSelection;
            std::vector<std::uint32_t> indexedSelection;
            std::size_t indexedInspections{};

            const double scanMs = milliseconds([&] {
                for (std::uint32_t i = 0; i < points.size(); ++i)
                    if (dirty.contains(regionKey(points[i], cellSize)))
                        scanSelection.push_back(i);
            });

            const double indexMs = milliseconds([&] {
                for (const Key& key : dirty) {
                    const auto found = index.find(key);
                    if (found == index.end())
                        continue;
                    indexedInspections += found->second.size();
                    indexedSelection.insert(indexedSelection.end(), found->second.begin(),
                                            found->second.end());
                }
            });

            std::sort(scanSelection.begin(), scanSelection.end());
            std::sort(indexedSelection.begin(), indexedSelection.end());
            const bool equal = scanSelection == indexedSelection;

            std::cout << count << ',' << fraction << ',' << index.size() << ',' << dirtyCount << ','
                      << scanSelection.size() << ',' << count << ',' << indexedInspections << ','
                      << std::fixed << std::setprecision(4) << buildMs << ',' << scanMs << ','
                      << indexMs << ',' << (equal ? 1 : 0) << '\n';
        }
    }
}
