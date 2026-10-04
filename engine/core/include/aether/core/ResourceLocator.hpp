#pragma once

#include <aether/core/Error.hpp>

#include <filesystem>
#include <string_view>
#include <vector>

namespace aether {

class ResourceLocator final {
  public:
    void addRoot(std::filesystem::path root);
    [[nodiscard]] Result<std::filesystem::path> find(std::string_view relativePath) const;

  private:
    std::vector<std::filesystem::path> roots_;
};

} // namespace aether
