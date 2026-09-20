#include <aether/world/LocalityLedger.hpp>

#include <array>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>
#include <string>

namespace {

using aether::world::LocalityDomain;
using aether::world::LocalityLedger;

int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testIndependentRatiosAndJson() {
    LocalityLedger ledger;
    expect(ledger.set(LocalityDomain::gaussiansInspected, 10, 1000).has_value(),
           "Gaussian inspection counter must accept a valid reference pair");
    expect(ledger.set(LocalityDomain::gpuPublicationBytes, 4096, 1'048'576).has_value(),
           "GPU byte counter must accept a valid reference pair");

    const auto gaussian = ledger.counter(LocalityDomain::gaussiansInspected).ratio();
    const auto bytes = ledger.counter(LocalityDomain::gpuPublicationBytes).ratio();
    expect(gaussian.has_value() && *gaussian == 0.01,
           "Gaussian ULR must remain a per-domain ratio");
    expect(bytes.has_value() && *bytes == 0.00390625,
           "GPU byte ULR must remain independent of Gaussian work");

    const auto json = ledger.toJson();
    expect(json.has_value(), "valid locality ledger must serialize");
    if (!json)
        return;
    expect(json->find("\"gaussiansInspected\":{\"incremental\":10,\"full\":1000") !=
               std::string::npos,
           "serialized ledger must preserve raw Gaussian counters");
    expect(json->find(
               "\"textureTexelsWritten\":{\"incremental\":0,\"full\":0,\"ratio\":null}") !=
               std::string::npos,
           "not-applicable domains must serialize with null ratio");
    expect(json->find(
               "\"materialStatesUpdated\":{\"incremental\":0,\"full\":0,\"ratio\":null}") !=
               std::string::npos,
           "material-state domain must serialize independently");
}

void testZeroFullBaselineFailsClosed() {
    LocalityLedger ledger;
    expect(!ledger.set(LocalityDomain::tsdfBlocksRead, 1, 0).has_value(),
           "incremental work without a full baseline must be rejected");

    expect(ledger.addIncremental(LocalityDomain::meshCellsRegenerated, 1).has_value(),
           "incremental accumulation is allowed before the reference is attached");
    expect(!ledger.validate().has_value(),
           "unfinished counter pair must fail final ledger validation");
    expect(ledger.addFull(LocalityDomain::meshCellsRegenerated, 20).has_value(),
           "full baseline can be attached after instrumentation completes");
    expect(ledger.validate().has_value(),
           "ledger must validate after the matching full baseline is supplied");
}

void testOverflowFailsClosed() {
    LocalityLedger ledger;
    expect(ledger.addFull(LocalityDomain::archiveBytesWritten,
                          std::numeric_limits<std::uint64_t>::max()).has_value(),
           "maximum representable counter value must be accepted once");
    expect(!ledger.addFull(LocalityDomain::archiveBytesWritten, 1).has_value(),
           "counter overflow must return a bounded structured failure");
}

void testS1CoreCoverageRequiresEveryHeadlineLayer() {
    LocalityLedger ledger;
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

    for (const LocalityDomain domain : required)
        expect(ledger.set(domain, 1, 100).has_value(),
               "S1 core fixture must accept valid per-domain counters");
    expect(ledger.validateS1CoreCoverage().has_value(),
           "S1 coverage gate must pass when every core layer has a full baseline");

    LocalityLedger incomplete;
    for (const LocalityDomain domain : required) {
        if (domain == LocalityDomain::gpuPublicationBytes)
            continue;
        expect(incomplete.set(domain, 1, 100).has_value(),
               "incomplete S1 fixture must accept its available counters");
    }
    expect(!incomplete.validateS1CoreCoverage().has_value(),
           "S1 coverage gate must fail rather than silently omit GPU publication work");
}

void testInvalidDomainFailsClosed() {
    LocalityLedger ledger;
    const auto invalid = static_cast<LocalityDomain>(255);
    expect(!ledger.set(invalid, 0, 0).has_value(),
           "invalid locality domain must be rejected");
    expect(aether::world::localityDomainName(invalid) == "invalid",
           "invalid locality domain must have deterministic diagnostic name");
}

} // namespace

int main() noexcept {
    try {
        testIndependentRatiosAndJson();
        testZeroFullBaselineFailsClosed();
        testOverflowFailsClosed();
        testS1CoreCoverageRequiresEveryHeadlineLayer();
        testInvalidDomainFailsClosed();
    } catch (const std::exception& error) {
        std::cerr << "FAIL: unexpected exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "FAIL: unexpected non-standard exception\n";
        return EXIT_FAILURE;
    }

    if (failures == 0)
        std::cout << "Locality ledger tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
