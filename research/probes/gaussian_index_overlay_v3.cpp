#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <span>
#include <string>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;

struct Key final {
    std::int32_t x{};
    std::int32_t y{};
    std::int32_t z{};
    auto operator<=>(const Key&) const = default;
};

struct Entry final {
    Key key{};
    std::uint32_t index{};
    auto operator<=>(const Entry&) const = default;
};

static_assert(sizeof(Entry) == 16, "Probe assumes compact 16-byte key/index entry");

[[nodiscard]] double ms(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

[[nodiscard]] std::vector<Entry> buildFlat(std::span<const Key> keys) {
    std::vector<Entry> result;
    result.reserve(keys.size());
    for (std::size_t i = 0; i < keys.size(); ++i)
        result.push_back(Entry{keys[i], static_cast<std::uint32_t>(i)});
    std::sort(result.begin(), result.end());
    return result;
}

[[nodiscard]] std::pair<std::vector<Entry>::const_iterator, std::vector<Entry>::const_iterator>
rangeFor(const std::vector<Entry>& entries, const Key& key) {
    const Entry lo{key, 0};
    const Entry hi{key, UINT32_MAX};
    return {std::lower_bound(entries.begin(), entries.end(), lo),
            std::upper_bound(entries.begin(), entries.end(), hi)};
}

[[nodiscard]] std::vector<Key> occupiedKeys(const std::vector<Entry>& entries) {
    std::vector<Key> result;
    result.reserve(entries.size());
    for (const Entry& entry : entries) {
        if (result.empty() || result.back() != entry.key)
            result.push_back(entry.key);
    }
    return result;
}

[[nodiscard]] std::vector<Key> chooseDirty(const std::vector<Entry>& current,
                                           double dirtyFraction) {
    const auto occupied = occupiedKeys(current);
    const std::size_t wanted = std::max<std::size_t>(
        1, static_cast<std::size_t>(std::ceil(occupied.size() * dirtyFraction)));
    std::vector<Key> dirty;
    dirty.reserve(wanted);
    // Deterministic evenly-spaced sampling avoids depending on hash/container order.
    for (std::size_t i = 0; i < wanted; ++i) {
        const std::size_t at = std::min<std::size_t>(
            occupied.size() - 1,
            (i * occupied.size()) / wanted);
        dirty.push_back(occupied[at]);
    }
    std::sort(dirty.begin(), dirty.end());
    dirty.erase(std::unique(dirty.begin(), dirty.end()), dirty.end());
    return dirty;
}

[[nodiscard]] std::vector<std::uint32_t> queryFlat(const std::vector<Entry>& flat,
                                                   std::span<const Key> dirty) {
    std::vector<std::uint32_t> result;
    for (const Key& key : dirty) {
        const auto [first, last] = rangeFor(flat, key);
        for (auto it = first; it != last; ++it)
            result.push_back(it->index);
    }
    std::sort(result.begin(), result.end());
    return result;
}

[[nodiscard]] std::vector<Entry> buildDelta(std::span<const Key> currentKeys,
                                            std::span<const std::uint32_t> changedIndices) {
    std::vector<Entry> delta;
    delta.reserve(changedIndices.size());
    for (const std::uint32_t index : changedIndices)
        delta.push_back(Entry{currentKeys[index], index});
    std::sort(delta.begin(), delta.end());
    return delta;
}

[[nodiscard]] std::vector<std::uint32_t>
queryOverlay(const std::vector<Entry>& base,
             const std::vector<Entry>& delta,
             std::span<const std::uint8_t> movedFromBase,
             std::span<const Key> dirty) {
    std::vector<std::uint32_t> result;
    for (const Key& key : dirty) {
        const auto [bf, bl] = rangeFor(base, key);
        for (auto it = bf; it != bl; ++it) {
            if (movedFromBase[it->index] == 0)
                result.push_back(it->index);
        }
        const auto [df, dl] = rangeFor(delta, key);
        for (auto it = df; it != dl; ++it)
            result.push_back(it->index);
    }
    std::sort(result.begin(), result.end());
    return result;
}

[[nodiscard]] double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    if (values.size() % 2 == 1)
        return values[values.size() / 2];
    return 0.5 * (values[values.size() / 2 - 1] + values[values.size() / 2]);
}

} // namespace

int main() try {
    constexpr std::size_t gaussianCount = 1'000'000;
    constexpr double dirtyFraction = 0.01;
    constexpr int queryRepeats = 7;
    constexpr std::uint32_t coordinateExtent = 512;
    constexpr std::uint64_t seed = 42;
    constexpr std::array<double, 6> fractions{0.01, 0.02, 0.05, 0.10, 0.20, 0.40};

    std::mt19937_64 rng(seed);
    std::uniform_int_distribution<std::int32_t> cell(0, coordinateExtent - 1);

    std::vector<Key> baseKeys(gaussianCount);
    for (Key& key : baseKeys)
        key = Key{cell(rng), cell(rng), cell(rng)};

    const auto baseBuildStart = Clock::now();
    const std::vector<Entry> base = buildFlat(baseKeys);
    const auto baseBuildEnd = Clock::now();

    std::vector<std::uint32_t> permutation(gaussianCount);
    std::iota(permutation.begin(), permutation.end(), 0U);
    std::shuffle(permutation.begin(), permutation.end(), rng);

    std::vector<Key> movedTarget(gaussianCount);
    for (Key& key : movedTarget)
        key = Key{cell(rng), cell(rng), cell(rng)};

    std::cout << std::fixed << std::setprecision(6);
    std::cout << "{\n"
              << "  \"schemaVersion\": 1,\n"
              << "  \"experiment\": \"gaussian-index-overlay-v3\",\n"
              << "  \"status\": \"synthetic-linux-x86-probe\",\n"
              << "  \"warning\": \"Not Apple-silicon, not Metal, and not a production scene benchmark. Timings are structural evidence only.\",\n"
              << "  \"configuration\": {\"gaussians\": " << gaussianCount
              << ", \"cellCoordinateExtent\": " << coordinateExtent
              << ", \"dirtyOccupiedCellFraction\": " << dirtyFraction
              << ", \"queryRepeats\": " << queryRepeats
              << ", \"seed\": " << seed << "},\n"
              << "  \"baseBuildMs\": " << ms(baseBuildStart, baseBuildEnd) << ",\n"
              << "  \"baseStorageBytes\": " << base.capacity() * sizeof(Entry) << ",\n"
              << "  \"entryBytes\": " << sizeof(Entry) << ",\n"
              << "  \"levels\": [\n";

    for (std::size_t level = 0; level < fractions.size(); ++level) {
        const double fraction = fractions[level];
        const std::size_t changedCount = static_cast<std::size_t>(gaussianCount * fraction);

        std::vector<Key> currentKeys = baseKeys;
        std::vector<std::uint8_t> moved(gaussianCount, 0);
        std::vector<std::uint32_t> changed;
        changed.reserve(changedCount);
        for (std::size_t i = 0; i < changedCount; ++i) {
            const std::uint32_t index = permutation[i];
            moved[index] = 1;
            currentKeys[index] = movedTarget[index];
            changed.push_back(index);
        }

        const auto oracleBuildStart = Clock::now();
        const std::vector<Entry> oracle = buildFlat(currentKeys);
        const auto oracleBuildEnd = Clock::now();

        const auto deltaBuildStart = Clock::now();
        const std::vector<Entry> delta = buildDelta(currentKeys, changed);
        const auto deltaBuildEnd = Clock::now();

        const std::vector<Key> dirty = chooseDirty(oracle, dirtyFraction);

        const auto oracleSelected = queryFlat(oracle, dirty);
        const auto overlaySelected = queryOverlay(base, delta, moved, dirty);
        const bool exact = oracleSelected == overlaySelected;
        if (!exact) {
            std::cerr << "overlay selection mismatch at fraction " << fraction << '\n';
            return EXIT_FAILURE;
        }

        std::vector<double> oracleQuery;
        std::vector<double> overlayQuery;
        oracleQuery.reserve(queryRepeats);
        overlayQuery.reserve(queryRepeats);
        std::size_t checksum{};
        for (int repeat = 0; repeat < queryRepeats; ++repeat) {
            auto a = Clock::now();
            auto selected = queryFlat(oracle, dirty);
            auto b = Clock::now();
            checksum += selected.size();
            oracleQuery.push_back(ms(a, b));

            a = Clock::now();
            selected = queryOverlay(base, delta, moved, dirty);
            b = Clock::now();
            checksum += selected.size();
            overlayQuery.push_back(ms(a, b));
        }
        if (checksum == 0) {
            std::cerr << "invalid zero selection checksum\n";
            return EXIT_FAILURE;
        }

        const std::size_t overlayStorage =
            base.capacity() * sizeof(Entry) +
            delta.capacity() * sizeof(Entry) +
            moved.capacity() * sizeof(std::uint8_t);
        const std::size_t oracleStorage = oracle.capacity() * sizeof(Entry);

        std::cout << "    {\"changedFraction\": " << fraction
                  << ", \"changedGaussians\": " << changedCount
                  << ", \"dirtyRegions\": " << dirty.size()
                  << ", \"selectedGaussians\": " << oracleSelected.size()
                  << ", \"fullRebuildMs\": " << ms(oracleBuildStart, oracleBuildEnd)
                  << ", \"deltaRebuildMs\": " << ms(deltaBuildStart, deltaBuildEnd)
                  << ", \"oracleQueryMedianMs\": " << median(oracleQuery)
                  << ", \"overlayQueryMedianMs\": " << median(overlayQuery)
                  << ", \"oracleStorageBytes\": " << oracleStorage
                  << ", \"overlayStorageBytes\": " << overlayStorage
                  << ", \"exactSelectionAgreement\": true}"
                  << (level + 1 == fractions.size() ? "\n" : ",\n");
    }

    std::cout << "  ]\n}\n";
    return EXIT_SUCCESS;
} catch (const std::exception& error) {
    std::cerr << "probe exception: " << error.what() << '\n';
    return EXIT_FAILURE;
} catch (...) {
    std::cerr << "probe unknown exception\n";
    return EXIT_FAILURE;
}
