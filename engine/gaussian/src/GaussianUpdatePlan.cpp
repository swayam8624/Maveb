#include <aether/gaussian/GaussianUpdatePlan.hpp>

#include <algorithm>
#include <limits>
#include <vector>

namespace aether::gaussian {

Result<GaussianPublicationPlan>
planGaussianPublication(std::span<const std::uint32_t> indices, std::size_t recordCount,
                        std::size_t recordBytes) {
    if (recordBytes == 0)
        return fail(ErrorCode::invalidArgument, "Gaussian publication record size must be positive");
    if (recordCount > std::numeric_limits<std::size_t>::max() / recordBytes)
        return fail(ErrorCode::resourceExhausted, "Gaussian full-buffer byte count overflows");

    GaussianPublicationPlan result;
    result.fullBufferBytes = recordCount * recordBytes;
    if (indices.empty())
        return result;

    std::vector<std::uint32_t> sorted(indices.begin(), indices.end());
    std::sort(sorted.begin(), sorted.end());

    if (std::adjacent_find(sorted.begin(), sorted.end()) != sorted.end()) {
        return fail(ErrorCode::invalidArgument,
                    "Gaussian publication indices must be unique");
    }
    if (static_cast<std::size_t>(sorted.back()) >= recordCount)
        return fail(ErrorCode::invalidArgument,
                    "Gaussian publication index is out of range");

    result.touchedRecords = sorted.size();
    if (result.touchedRecords > std::numeric_limits<std::size_t>::max() / recordBytes)
        return fail(ErrorCode::resourceExhausted, "Gaussian touched-byte count overflows");
    result.touchedBytes = result.touchedRecords * recordBytes;

    std::uint32_t first = sorted.front();
    std::uint32_t previous = first;
    for (std::size_t i = 1; i < sorted.size(); ++i) {
        const std::uint32_t current = sorted[i];
        if (current == previous + 1U) {
            previous = current;
            continue;
        }
        result.ranges.push_back(
            GaussianPublicationRange{first, previous - first + 1U});
        first = current;
        previous = current;
    }
    result.ranges.push_back(GaussianPublicationRange{first, previous - first + 1U});
    return result;
}

} // namespace aether::gaussian
