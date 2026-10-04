#include <aether/core/Diagnostics.hpp>

#include <aether/core/Log.hpp>

#include <sys/sysctl.h>
#include <sys/utsname.h>

#include <fstream>
#include <sstream>

namespace aether {
namespace {

std::string escape(std::string_view value) {
    std::string output;
    output.reserve(value.size());
    for (const char character : value) {
        switch (character) {
        case '"':
            output += "\\\"";
            break;
        case '\\':
            output += "\\\\";
            break;
        case '\n':
            output += "\\n";
            break;
        case '\r':
            output += "\\r";
            break;
        case '\t':
            output += "\\t";
            break;
        default:
            if (static_cast<unsigned char>(character) >= 0x20U) {
                output += character;
            }
        }
    }
    return output;
}

std::string sysctlString(const char* name) {
    std::size_t size = 0;
    if (sysctlbyname(name, nullptr, &size, nullptr, 0) != 0 || size == 0) {
        return "unknown";
    }
    std::string value(size, '\0');
    if (sysctlbyname(name, value.data(), &size, nullptr, 0) != 0) {
        return "unknown";
    }
    while (!value.empty() && value.back() == '\0') {
        value.pop_back();
    }
    return value;
}

std::uint64_t physicalMemory() {
    std::uint64_t value = 0;
    std::size_t size = sizeof(value);
    if (sysctlbyname("hw.memsize", &value, &size, nullptr, 0) != 0) {
        return 0;
    }
    return value;
}

const char* levelName(LogLevel level) {
    switch (level) {
    case LogLevel::debug:
        return "debug";
    case LogLevel::info:
        return "info";
    case LogLevel::warning:
        return "warning";
    case LogLevel::error:
        return "error";
    }
    return "unknown";
}

} // namespace

Result<void> Diagnostics::writeReport(const std::filesystem::path& destination,
                                      const DiagnosticsContext& context) {
    if (destination.empty()) {
        return fail(ErrorCode::invalidArgument, "Diagnostics destination cannot be empty");
    }

    struct utsname system{};
    const bool hasSystem = uname(&system) == 0;
    const auto temporary = destination.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    if (!stream) {
        return fail(ErrorCode::io, "Unable to create diagnostics report", destination.string());
    }

    stream << "{\n  \"schemaVersion\": 1,\n"
           << "  \"applicationVersion\": \"" << escape(context.applicationVersion) << "\",\n"
           << "  \"operatingSystem\": \""
           << escape(hasSystem ? std::string(system.sysname) + " " + system.release : "unknown")
           << "\",\n"
           << "  \"hardwareModel\": \"" << escape(sysctlString("hw.model")) << "\",\n"
           << "  \"physicalMemoryBytes\": " << physicalMemory() << ",\n"
           << "  \"fields\": {";
    for (std::size_t index = 0; index < context.fields.size(); ++index) {
        const auto& [key, value] = context.fields[index];
        stream << (index == 0 ? "\n" : ",\n") << "    \"" << escape(key) << "\": \""
               << escape(value) << "\"";
    }
    stream << (context.fields.empty() ? "" : "\n  ") << "},\n  \"logs\": [";

    const auto logs = Log::instance().snapshot();
    for (std::size_t index = 0; index < logs.size(); ++index) {
        const auto& record = logs[index];
        stream << (index == 0 ? "\n" : ",\n") << "    {\"timeMs\": " << record.unixMilliseconds
               << ", \"level\": \"" << levelName(record.level) << "\", \"message\": \""
               << escape(record.message) << "\"}";
    }
    stream << (logs.empty() ? "" : "\n  ") << "]\n}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Failed while writing diagnostics report", destination.string());
    }

    std::error_code error;
    std::filesystem::rename(temporary, destination, error);
    if (error) {
        std::filesystem::remove(temporary);
        return fail(ErrorCode::io, "Unable to finalize diagnostics report", error.message());
    }
    return {};
}

} // namespace aether
