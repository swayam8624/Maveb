#include <aether/core/ResourceLocator.hpp>

namespace aether {

void ResourceLocator::addRoot(std::filesystem::path root) {
    roots_.push_back(std::filesystem::weakly_canonical(std::move(root)));
}

Result<std::filesystem::path> ResourceLocator::find(std::string_view relativePath) const {
    const std::filesystem::path requested(relativePath);
    if (requested.is_absolute() || relativePath.find("..") != std::string_view::npos) {
        return fail(ErrorCode::invalidArgument, "Resource paths must be safe and relative",
                    std::string(relativePath));
    }

    for (const auto& root : roots_) {
        auto candidate = root / requested;
        std::error_code error;
        if (std::filesystem::is_regular_file(candidate, error) && !error) {
            return std::filesystem::weakly_canonical(candidate);
        }
    }
    return fail(ErrorCode::notFound, "Resource was not found", std::string(relativePath));
}
} // namespace aether
