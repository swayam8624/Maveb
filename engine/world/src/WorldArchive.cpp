#include <aether/world/WorldArchive.hpp>

#include <simdjson.h>

#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>
#include <string_view>

namespace aether::world {
namespace {

void writeEscapedString(std::ostream& stream, std::string_view value) {
    constexpr char hexadecimal[] = "0123456789abcdef";
    stream << '"';
    for (const unsigned char character : value) {
        switch (character) {
        case '"':
            stream << "\\\"";
            break;
        case '\\':
            stream << "\\\\";
            break;
        case '\b':
            stream << "\\b";
            break;
        case '\f':
            stream << "\\f";
            break;
        case '\n':
            stream << "\\n";
            break;
        case '\r':
            stream << "\\r";
            break;
        case '\t':
            stream << "\\t";
            break;
        default:
            if (character < 0x20U) {
                stream << "\\u00" << hexadecimal[(character >> 4U) & 0x0FU]
                       << hexadecimal[character & 0x0FU];
            } else {
                stream << static_cast<char>(character);
            }
            break;
        }
    }
    stream << '"';
}

void writeFloat3(std::ostream& stream, simd_float3 value) {
    stream << '[' << value.x << ',' << value.y << ',' << value.z << ']';
}

void writeFloat4(std::ostream& stream, simd_float4 value) {
    stream << '[' << value.x << ',' << value.y << ',' << value.z << ',' << value.w << ']';
}

Result<void> validateArchiveState(const WorldTimeline& timeline, std::uint64_t nextEntityId) {
    TimestampNs previousTimestamp{};
    std::uint64_t maximumEntityId{};
    std::uint64_t expectedRevision{1};
    for (const WorldSnapshot& snapshot : timeline.snapshots()) {
        if (snapshot.revision != expectedRevision)
            return fail(ErrorCode::corruptData, "World archive revisions must be contiguous");
        if (snapshot.timestamp == 0 || snapshot.timestamp <= previousTimestamp)
            return fail(ErrorCode::corruptData, "World archive timestamps must be strictly increasing");
        if (auto validation = validateSnapshot(snapshot); !validation)
            return validation;
        for (const EntityState& entity : snapshot.entities)
            maximumEntityId = std::max(maximumEntityId, entity.id.value);
        previousTimestamp = snapshot.timestamp;
        ++expectedRevision;
    }
    if (nextEntityId != 0 && nextEntityId <= maximumEntityId) {
        return fail(ErrorCode::corruptData,
                    "World archive next entity ID must be newer than every committed entity ID");
    }
    return {};
}

Result<std::uint64_t> readUnsigned(simdjson::dom::element object, const char* field) {
    std::uint64_t value{};
    if (object[field].get(value))
        return fail(ErrorCode::corruptData, "World archive integer field is missing", field);
    return value;
}

Result<float> readFloat(simdjson::dom::element object, const char* field) {
    double value{};
    if (object[field].get(value) || !std::isfinite(value) ||
        value < -static_cast<double>(std::numeric_limits<float>::max()) ||
        value > static_cast<double>(std::numeric_limits<float>::max())) {
        return fail(ErrorCode::corruptData, "World archive numeric field is invalid", field);
    }
    return static_cast<float>(value);
}

Result<std::string> readString(simdjson::dom::element object, const char* field) {
    std::string_view value;
    if (object[field].get(value))
        return fail(ErrorCode::corruptData, "World archive string field is missing", field);
    return std::string(value);
}

Result<simd_float3> readFloat3(simdjson::dom::element object, const char* field) {
    simdjson::dom::array array;
    if (object[field].get_array().get(array) || array.size() != 3)
        return fail(ErrorCode::corruptData, "World archive float3 field is invalid", field);
    simd_float3 result{};
    std::size_t index{};
    for (simdjson::dom::element element : array) {
        double value{};
        if (element.get(value) || !std::isfinite(value) ||
            value < -static_cast<double>(std::numeric_limits<float>::max()) ||
            value > static_cast<double>(std::numeric_limits<float>::max())) {
            return fail(ErrorCode::corruptData, "World archive float3 contains invalid number", field);
        }
        result[index++] = static_cast<float>(value);
    }
    return result;
}

Result<simd_float4> readFloat4(simdjson::dom::element object, const char* field) {
    simdjson::dom::array array;
    if (object[field].get_array().get(array) || array.size() != 4)
        return fail(ErrorCode::corruptData, "World archive float4 field is invalid", field);
    simd_float4 result{};
    std::size_t index{};
    for (simdjson::dom::element element : array) {
        double value{};
        if (element.get(value) || !std::isfinite(value) ||
            value < -static_cast<double>(std::numeric_limits<float>::max()) ||
            value > static_cast<double>(std::numeric_limits<float>::max())) {
            return fail(ErrorCode::corruptData, "World archive float4 contains invalid number", field);
        }
        result[index++] = static_cast<float>(value);
    }
    return result;
}

Result<EntityState> readEntity(simdjson::dom::element element) {
    auto id = readUnsigned(element, "id");
    auto name = readString(element, "name");
    auto semanticLabel = readString(element, "semanticLabel");
    auto translation = readFloat3(element, "translation");
    auto rotation = readFloat4(element, "rotation");
    auto scale = readFloat3(element, "scale");
    auto boundsMinimum = readFloat3(element, "boundsMinimum");
    auto boundsMaximum = readFloat3(element, "boundsMaximum");
    auto representation = readUnsigned(element, "representation");
    auto geometrySignature = readUnsigned(element, "geometrySignature");
    auto appearanceSignature = readUnsigned(element, "appearanceSignature");
    auto confidence = readFloat(element, "confidence");
    auto lastObserved = readUnsigned(element, "lastObserved");
    if (!id)
        return std::unexpected(id.error());
    if (!name)
        return std::unexpected(name.error());
    if (!semanticLabel)
        return std::unexpected(semanticLabel.error());
    if (!translation)
        return std::unexpected(translation.error());
    if (!rotation)
        return std::unexpected(rotation.error());
    if (!scale)
        return std::unexpected(scale.error());
    if (!boundsMinimum)
        return std::unexpected(boundsMinimum.error());
    if (!boundsMaximum)
        return std::unexpected(boundsMaximum.error());
    if (!representation)
        return std::unexpected(representation.error());
    if (!geometrySignature)
        return std::unexpected(geometrySignature.error());
    if (!appearanceSignature)
        return std::unexpected(appearanceSignature.error());
    if (!confidence)
        return std::unexpected(confidence.error());
    if (!lastObserved)
        return std::unexpected(lastObserved.error());
    if (*representation > static_cast<std::uint64_t>(RepresentationKind::volumetric))
        return fail(ErrorCode::corruptData, "World archive representation kind is unsupported");

    EntityState entity;
    entity.id = EntityId{*id};
    entity.name = std::move(*name);
    entity.semanticLabel = std::move(*semanticLabel);
    entity.transform.translation = *translation;
    entity.transform.rotation = simd_quaternion((*rotation).x, (*rotation).y, (*rotation).z,
                                                (*rotation).w);
    entity.transform.scale = *scale;
    entity.worldBounds = Bounds{*boundsMinimum, *boundsMaximum};
    entity.representation = static_cast<RepresentationKind>(*representation);
    entity.geometrySignature = *geometrySignature;
    entity.appearanceSignature = *appearanceSignature;
    entity.confidence = *confidence;
    entity.lastObserved = *lastObserved;
    return entity;
}

} // namespace

Result<void> saveWorldArchive(const std::filesystem::path& path, const WorldTimeline& timeline,
                              std::uint64_t nextEntityId) {
    if (path.empty())
        return fail(ErrorCode::invalidArgument, "World archive destination is empty");
    if (auto validation = validateArchiveState(timeline, nextEntityId); !validation)
        return validation;

    const std::filesystem::path temporary = path.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    if (!stream)
        return fail(ErrorCode::io, "Unable to open temporary world archive", temporary.string());
    stream << std::setprecision(std::numeric_limits<float>::max_digits10);
    stream << "{\n  \"schemaVersion\":" << worldArchiveSchemaVersion
           << ",\n  \"nextEntityId\":" << nextEntityId << ",\n  \"snapshots\":[\n";

    const auto& snapshots = timeline.snapshots();
    for (std::size_t snapshotIndex = 0; snapshotIndex < snapshots.size(); ++snapshotIndex) {
        const WorldSnapshot& snapshot = snapshots[snapshotIndex];
        stream << "    {\"revision\":" << snapshot.revision << ",\"timestamp\":"
               << snapshot.timestamp << ",\"entities\":[\n";
        for (std::size_t entityIndex = 0; entityIndex < snapshot.entities.size(); ++entityIndex) {
            const EntityState& entity = snapshot.entities[entityIndex];
            const simd_float4 rotation = entity.transform.rotation.vector;
            stream << "      {\"id\":" << entity.id.value << ",\"name\":";
            writeEscapedString(stream, entity.name);
            stream << ",\"semanticLabel\":";
            writeEscapedString(stream, entity.semanticLabel);
            stream << ",\"translation\":";
            writeFloat3(stream, entity.transform.translation);
            stream << ",\"rotation\":";
            writeFloat4(stream, rotation);
            stream << ",\"scale\":";
            writeFloat3(stream, entity.transform.scale);
            stream << ",\"boundsMinimum\":";
            writeFloat3(stream, entity.worldBounds.minimum);
            stream << ",\"boundsMaximum\":";
            writeFloat3(stream, entity.worldBounds.maximum);
            stream << ",\"representation\":" << static_cast<std::uint64_t>(entity.representation)
                   << ",\"geometrySignature\":" << entity.geometrySignature
                   << ",\"appearanceSignature\":" << entity.appearanceSignature
                   << ",\"confidence\":" << entity.confidence << ",\"lastObserved\":"
                   << entity.lastObserved << '}';
            stream << (entityIndex + 1 == snapshot.entities.size() ? "\n" : ",\n");
        }
        stream << "    ]}" << (snapshotIndex + 1 == snapshots.size() ? "\n" : ",\n");
    }
    stream << "  ]\n}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to write world archive", path.string());
    }

    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to finalize world archive", error.message());
    }
    return {};
}

Result<WorldArchiveData> loadWorldArchive(const std::filesystem::path& path,
                                          WorldArchiveLimits limits) {
    if (path.empty())
        return fail(ErrorCode::invalidArgument, "World archive path is empty");
    if (limits.maximumSnapshots == 0 || limits.maximumEntitiesPerSnapshot == 0 ||
        limits.maximumTotalEntities == 0) {
        return fail(ErrorCode::invalidArgument, "World archive resource limits must be non-zero");
    }

    simdjson::dom::parser parser;
    auto parsed = parser.load(path.string());
    if (parsed.error()) {
        return fail(ErrorCode::corruptData, "Unable to parse world archive JSON",
                    simdjson::error_message(parsed.error()));
    }
    simdjson::dom::element document = parsed.value();
    auto schemaVersion = readUnsigned(document, "schemaVersion");
    auto nextEntityId = readUnsigned(document, "nextEntityId");
    if (!schemaVersion)
        return std::unexpected(schemaVersion.error());
    if (!nextEntityId)
        return std::unexpected(nextEntityId.error());
    if (*schemaVersion != worldArchiveSchemaVersion)
        return fail(ErrorCode::unsupported, "World archive schema version is unsupported");

    simdjson::dom::array snapshots;
    if (document["snapshots"].get_array().get(snapshots) || snapshots.size() > limits.maximumSnapshots)
        return fail(ErrorCode::resourceExhausted, "World archive snapshot count exceeds limits");

    WorldArchiveData result;
    result.nextEntityId = *nextEntityId;
    result.snapshots.reserve(snapshots.size());
    std::size_t totalEntities{};
    std::uint64_t maximumEntityId{};
    TimestampNs previousTimestamp{};
    std::uint64_t expectedRevision{1};

    for (simdjson::dom::element snapshotElement : snapshots) {
        auto revision = readUnsigned(snapshotElement, "revision");
        auto timestamp = readUnsigned(snapshotElement, "timestamp");
        if (!revision)
            return std::unexpected(revision.error());
        if (!timestamp)
            return std::unexpected(timestamp.error());
        if (*revision != expectedRevision || *timestamp == 0 || *timestamp <= previousTimestamp)
            return fail(ErrorCode::corruptData, "World archive timeline ordering is invalid");

        simdjson::dom::array entities;
        if (snapshotElement["entities"].get_array().get(entities) ||
            entities.size() > limits.maximumEntitiesPerSnapshot ||
            totalEntities > limits.maximumTotalEntities - entities.size()) {
            return fail(ErrorCode::resourceExhausted, "World archive entity count exceeds limits");
        }

        WorldSnapshot snapshot;
        snapshot.revision = *revision;
        snapshot.timestamp = *timestamp;
        snapshot.entities.reserve(entities.size());
        for (simdjson::dom::element entityElement : entities) {
            auto entity = readEntity(entityElement);
            if (!entity)
                return std::unexpected(entity.error());
            maximumEntityId = std::max(maximumEntityId, entity->id.value);
            snapshot.entities.push_back(std::move(*entity));
        }
        if (auto validation = validateSnapshot(snapshot); !validation)
            return std::unexpected(validation.error());
        totalEntities += snapshot.entities.size();
        previousTimestamp = snapshot.timestamp;
        ++expectedRevision;
        result.snapshots.push_back(std::move(snapshot));
    }

    if (result.nextEntityId != 0 && result.nextEntityId <= maximumEntityId) {
        return fail(ErrorCode::corruptData,
                    "World archive next entity ID collides with committed entity identity");
    }
    return result;
}

} // namespace aether::world
