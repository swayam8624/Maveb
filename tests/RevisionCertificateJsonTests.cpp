#include <aether/revision/RevisionCertificateJson.hpp>

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

using namespace aether::revision;
int failures{};

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void testDeterministicNativeCertificateJson() {
    auto graph = RevisionGraph::build(
        {
            {"edit \"source\"", 1.0, 0.5},
            {"history", 2.0, 0.0},
            {"output", 0.0, 0.0},
        },
        {
            {0, 2, RevisionEdgeClass::analytic, 0.25, "gaussian-bound"},
            {1, 2, RevisionEdgeClass::analytic, 0.5, "temporal-bound"},
        },
        10.0);
    expect(graph.has_value(), "certificate JSON fixture graph must build");
    if (!graph)
        return;

    const std::vector<double> source{0.0, 0.1, 0.0};
    const std::vector<RevisionNodeId> cone{0};
    const std::vector<RevisionQoI> qois{
        {"rgb", {{2, 1.0}}, 0.2},
    };
    auto certificate = certifyRevisionCone(*graph, source, cone, qois);
    expect(certificate.has_value(), "certificate JSON fixture must certify");
    if (!certificate)
        return;

    auto json = serializeRevisionCertificateJson(*graph, *certificate,
                                                 {
                                                     .graphVersion = "captured-world-v1",
                                                     .boundVersion = "gaussian-temporal-v1",
                                                     .costModelVersion = "fixture-ms-v1",
                                                 });
    expect(json.has_value(), "certificate JSON serialization must succeed");
    if (!json)
        return;

    expect(json->find("\"schemaVersion\":1") != std::string::npos,
           "certificate JSON must expose schema version");
    expect(json->find("\"artifact\":\"maveb-cbrc-native-certificate\"") != std::string::npos,
           "certificate JSON must expose artifact type");
    expect(json->find("edit \\\"source\\\"") != std::string::npos,
           "certificate JSON must escape node names");
    expect(json->find("\"work\":1") != std::string::npos &&
               json->find("\"fullWork\":10") != std::string::npos &&
               json->find("\"workRatioFull\":") != std::string::npos,
           "certificate JSON must preserve independent FULL baseline");
    expect(json->find("\"name\":\"rgb\"") != std::string::npos,
           "certificate JSON must include QoI result");
}

void testMetadataIsMandatory() {
    auto graph = RevisionGraph::build({{"node", 1.0, 0.0}}, {});
    expect(graph.has_value(), "metadata test graph must build");
    if (!graph)
        return;

    RevisionConeCertificate certificate;
    certificate.cone = {0};
    certificate.stable = true;
    certificate.passes = true;
    certificate.work = 1.0;
    certificate.fullWork = 1.0;

    auto json = serializeRevisionCertificateJson(*graph, certificate,
                                                 {
                                                     .graphVersion = "",
                                                     .boundVersion = "bounds",
                                                     .costModelVersion = "costs",
                                                 });
    expect(!json.has_value(), "certificate JSON must reject missing provenance versions");
}

} // namespace

int main() noexcept {
    testDeterministicNativeCertificateJson();
    testMetadataIsMandatory();
    if (failures == 0)
        std::cout << "Revision certificate JSON tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
