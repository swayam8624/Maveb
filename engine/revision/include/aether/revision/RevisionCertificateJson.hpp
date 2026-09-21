#pragma once

#include <aether/revision/RevisionPlanner.hpp>

#include <string>

namespace aether::revision {

struct RevisionCertificateMetadata final {
    std::string graphVersion;
    std::string boundVersion;
    std::string costModelVersion;
};

/// Deterministic JSON representation of one native CBRC planner result.
///
/// This serializer is intentionally dependency-free and stable for regression
/// artifacts. Node IDs are sorted, QoIs preserve planner order, and every node
/// carries both its numeric ID and graph name.
[[nodiscard]] Result<std::string>
serializeRevisionCertificateJson(const RevisionGraph& graph,
                                 const RevisionConeCertificate& certificate,
                                 const RevisionCertificateMetadata& metadata);

} // namespace aether::revision
