#pragma once

#include <aether/core/Error.hpp>

#include <filesystem>
#include <string>
#include <utility>
#include <vector>

namespace aether {

struct DiagnosticsContext {
    std::string applicationVersion;
    std::vector<std::pair<std::string, std::string>> fields;
};

class Diagnostics final {
  public:
    /// Writes a privacy-minimized JSON report atomically. The default report contains operating
    /// system, hardware model, physical memory, caller-supplied renderer fields, and retained
    /// AETHER logs. It intentionally excludes serial numbers, user names, and full home paths.
    [[nodiscard]] static Result<void> writeReport(const std::filesystem::path& destination,
                                                  const DiagnosticsContext& context);
};

} // namespace aether
