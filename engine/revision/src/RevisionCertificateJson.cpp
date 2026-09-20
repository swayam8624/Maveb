#include <aether/revision/RevisionCertificateJson.hpp>

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <string_view>
#include <vector>

namespace aether::revision {
namespace {

[[nodiscard]] std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size() + 8);
    for (const char ch : value) {
        switch (ch) {
        case '"':
        case '\\':
            result.push_back('\\');
            result.push_back(ch);
            break;
        case '\b':
            result += "\\b";
            break;
        case '\f':
            result += "\\f";
            break;
        case '\n':
            result += "\\n";
            break;
        case '\r':
            result += "\\r";
            break;
        case '\t':
            result += "\\t";
            break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20U) {
                std::ostringstream encoded;
                encoded << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                        << static_cast<unsigned int>(static_cast<unsigned char>(ch));
                result += encoded.str();
            } else {
                result.push_back(ch);
            }
        }
    }
    return result;
}

[[nodiscard]] bool finiteNonNegative(double value) noexcept {
    return std::isfinite(value) && value >= 0.0;
}

[[nodiscard]] Result<void>
validateCertificateForSerialization(const RevisionGraph& graph,
                                    const RevisionConeCertificate& certificate,
                                    const RevisionCertificateMetadata& metadata) {
    if (metadata.graphVersion.empty() || metadata.boundVersion.empty() ||
        metadata.costModelVersion.empty()) {
        return fail(ErrorCode::invalidArgument,
                    "Revision certificate metadata versions must be non-empty");
    }
    if (!finiteNonNegative(certificate.work) || !finiteNonNegative(certificate.fullWork)) {
        return fail(ErrorCode::invalidArgument,
                    "Revision certificate work values must be finite and non-negative");
    }
    if (certificate.work > certificate.fullWork && certificate.fullRebuild) {
        return fail(ErrorCode::invalidArgument,
                    "Full-rebuild certificate work cannot exceed full baseline");
    }

    const auto validateIds = [&](const std::vector<RevisionNodeId>& ids,
                                 const char* label) -> Result<void> {
        for (const RevisionNodeId id : ids) {
            if (id >= graph.nodeCount())
                return fail(ErrorCode::invalidArgument,
                            "Revision certificate contains out-of-range node", label);
        }
        return {};
    };
    if (auto valid = validateIds(certificate.cone, "cone"); !valid)
        return std::unexpected(valid.error());
    if (auto valid = validateIds(certificate.exterior, "exterior"); !valid)
        return std::unexpected(valid.error());

    for (const RevisionQoIResult& qoi : certificate.qois) {
        if (qoi.name.empty() || !finiteNonNegative(qoi.epsilon) || !finiteNonNegative(qoi.bound)) {
            return fail(ErrorCode::invalidArgument, "Revision certificate QoI is not serializable");
        }
    }
    return {};
}

void appendNodeArray(std::ostringstream& output, const RevisionGraph& graph,
                     std::vector<RevisionNodeId> ids) {
    std::sort(ids.begin(), ids.end());
    ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
    output << '[';
    for (std::size_t index = 0; index < ids.size(); ++index) {
        if (index != 0)
            output << ',';
        const RevisionNodeId id = ids[index];
        output << "{\"id\":" << id << ",\"name\":\"" << escapeJson(graph.node(id).name) << "\"}";
    }
    output << ']';
}

} // namespace

Result<std::string> serializeRevisionCertificateJson(const RevisionGraph& graph,
                                                     const RevisionConeCertificate& certificate,
                                                     const RevisionCertificateMetadata& metadata) {
    if (auto valid = validateCertificateForSerialization(graph, certificate, metadata); !valid) {
        return std::unexpected(valid.error());
    }

    std::ostringstream output;
    output << std::setprecision(17);
    output << '{' << "\"schemaVersion\":1,"
           << "\"artifact\":\"maveb-cbrc-native-certificate\","
           << "\"graphVersion\":\"" << escapeJson(metadata.graphVersion) << "\","
           << "\"boundVersion\":\"" << escapeJson(metadata.boundVersion) << "\","
           << "\"costModelVersion\":\"" << escapeJson(metadata.costModelVersion) << "\","
           << "\"stable\":" << (certificate.stable ? "true" : "false") << ','
           << "\"passes\":" << (certificate.passes ? "true" : "false") << ','
           << "\"fullRebuild\":" << (certificate.fullRebuild ? "true" : "false") << ','
           << "\"reason\":\"" << escapeJson(certificate.reason) << "\","
           << "\"work\":" << certificate.work << ',' << "\"fullWork\":" << certificate.fullWork
           << ',' << "\"workRatioFull\":";
    if (certificate.fullWork == 0.0)
        output << "null";
    else
        output << certificate.work / certificate.fullWork;

    output << ",\"cone\":";
    appendNodeArray(output, graph, certificate.cone);
    output << ",\"exterior\":";
    appendNodeArray(output, graph, certificate.exterior);

    output << ",\"qois\":[";
    for (std::size_t index = 0; index < certificate.qois.size(); ++index) {
        if (index != 0)
            output << ',';
        const RevisionQoIResult& qoi = certificate.qois[index];
        output << "{\"name\":\"" << escapeJson(qoi.name) << "\","
               << "\"bound\":" << qoi.bound << ',' << "\"epsilon\":" << qoi.epsilon << ','
               << "\"passes\":" << (qoi.bound <= qoi.epsilon ? "true" : "false") << '}';
    }
    output << "]}\n";
    return output.str();
}

} // namespace aether::revision
