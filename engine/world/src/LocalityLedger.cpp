#include <aether/world/LocalityLedger.hpp>

#include <limits>
#include <sstream>

namespace aether::world {
namespace {

[[nodiscard]] bool addWouldOverflow(std::uint64_t lhs, std::uint64_t rhs) noexcept {
    return rhs > std::numeric_limits<std::uint64_t>::max() - lhs;
}

} // namespace

std::optional<double> LocalityCounter::ratio() const noexcept {
    if (full == 0)
        return std::nullopt;
    return static_cast<double>(incremental) / static_cast<double>(full);
}

std::string_view localityDomainName(LocalityDomain domain) noexcept {
    switch (domain) {
    case LocalityDomain::observationsInspected:
        return "observationsInspected";
    case LocalityDomain::tsdfBlocksRead:
        return "tsdfBlocksRead";
    case LocalityDomain::tsdfBlocksWritten:
        return "tsdfBlocksWritten";
    case LocalityDomain::tsdfBytesReadBack:
        return "tsdfBytesReadBack";
    case LocalityDomain::meshCellsRegenerated:
        return "meshCellsRegenerated";
    case LocalityDomain::meshPatchesRegenerated:
        return "meshPatchesRegenerated";
    case LocalityDomain::gaussiansInspected:
        return "gaussiansInspected";
    case LocalityDomain::gaussiansUpdated:
        return "gaussiansUpdated";
    case LocalityDomain::texturePagesUpdated:
        return "texturePagesUpdated";
    case LocalityDomain::textureSlotsConsidered:
        return "textureSlotsConsidered";
    case LocalityDomain::textureTexelsWritten:
        return "textureTexelsWritten";
    case LocalityDomain::materialStatesUpdated:
        return "materialStatesUpdated";
    case LocalityDomain::cpuToGpuBytes:
        return "cpuToGpuBytes";
    case LocalityDomain::gpuToCpuBytes:
        return "gpuToCpuBytes";
    case LocalityDomain::gpuPublicationBytes:
        return "gpuPublicationBytes";
    case LocalityDomain::temporalPixelsInvalidated:
        return "temporalPixelsInvalidated";
    case LocalityDomain::archiveBytesWritten:
        return "archiveBytesWritten";
    case LocalityDomain::count:
        break;
    }
    return "invalid";
}

Result<std::size_t> LocalityLedger::checkedIndex(LocalityDomain domain) {
    const auto index = static_cast<std::size_t>(domain);
    if (index >= static_cast<std::size_t>(LocalityDomain::count))
        return fail(ErrorCode::invalidArgument, "Locality ledger domain is out of range");
    return index;
}

Result<void> LocalityLedger::set(LocalityDomain domain, std::uint64_t incremental,
                                 std::uint64_t full) {
    auto index = checkedIndex(domain);
    if (!index)
        return std::unexpected(index.error());
    if (full == 0 && incremental != 0) {
        return fail(ErrorCode::invalidArgument,
                    "Locality ledger cannot record incremental work against a zero full baseline",
                    std::string(localityDomainName(domain)));
    }
    counters_[*index] = LocalityCounter{.incremental = incremental, .full = full};
    return {};
}

Result<void> LocalityLedger::addIncremental(LocalityDomain domain, std::uint64_t amount) {
    auto index = checkedIndex(domain);
    if (!index)
        return std::unexpected(index.error());
    auto& value = counters_[*index].incremental;
    if (addWouldOverflow(value, amount))
        return fail(ErrorCode::resourceExhausted, "Locality incremental counter overflow",
                    std::string(localityDomainName(domain)));
    value += amount;
    return {};
}

Result<void> LocalityLedger::addFull(LocalityDomain domain, std::uint64_t amount) {
    auto index = checkedIndex(domain);
    if (!index)
        return std::unexpected(index.error());
    auto& value = counters_[*index].full;
    if (addWouldOverflow(value, amount))
        return fail(ErrorCode::resourceExhausted, "Locality full-baseline counter overflow",
                    std::string(localityDomainName(domain)));
    value += amount;
    return {};
}

const LocalityCounter& LocalityLedger::counter(LocalityDomain domain) const noexcept {
    const auto index = static_cast<std::size_t>(domain);
    if (index >= counters_.size()) {
        static const LocalityCounter invalid{};
        return invalid;
    }
    return counters_[index];
}

Result<void> LocalityLedger::validate() const {
    for (std::size_t index = 0; index < counters_.size(); ++index) {
        const auto& value = counters_[index];
        if (value.full == 0 && value.incremental != 0) {
            return fail(
                ErrorCode::invalidArgument,
                "Locality ledger contains incremental work without an equivalent full baseline",
                std::string(localityDomainName(static_cast<LocalityDomain>(index))));
        }
    }
    return {};
}

Result<void> LocalityLedger::validateS1CoreCoverage() const {
    if (auto validation = validate(); !validation)
        return std::unexpected(validation.error());

    constexpr std::array required{
        LocalityDomain::observationsInspected,
        LocalityDomain::tsdfBlocksRead,
        LocalityDomain::tsdfBlocksWritten,
        LocalityDomain::meshCellsRegenerated,
        LocalityDomain::gaussiansInspected,
        LocalityDomain::gaussiansUpdated,
        LocalityDomain::texturePagesUpdated,
        LocalityDomain::textureTexelsWritten,
        LocalityDomain::materialStatesUpdated,
        LocalityDomain::gpuPublicationBytes,
        LocalityDomain::temporalPixelsInvalidated,
    };
    for (const LocalityDomain domain : required) {
        if (counter(domain).full == 0) {
            return fail(ErrorCode::invalidArgument,
                        "S1 locality certificate is missing a core full-reference baseline",
                        std::string(localityDomainName(domain)));
        }
    }
    return {};
}

Result<std::string> LocalityLedger::toJson() const {
    if (auto validation = validate(); !validation)
        return std::unexpected(validation.error());

    std::ostringstream output;
    output.precision(17);
    output << "{\"schemaVersion\":1,\"domains\":{";
    for (std::size_t index = 0; index < counters_.size(); ++index) {
        if (index != 0)
            output << ',';
        const auto domain = static_cast<LocalityDomain>(index);
        const auto& value = counters_[index];
        output << '\"' << localityDomainName(domain) << "\":{\"incremental\":"
               << value.incremental << ",\"full\":" << value.full << ",\"ratio\":";
        if (const auto ratio = value.ratio())
            output << *ratio;
        else
            output << "null";
        output << '}';
    }
    output << "}}";
    return output.str();
}

} // namespace aether::world
