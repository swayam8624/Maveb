#pragma once

#include <expected>
#include <string>
#include <utility>

namespace aether {

enum class ErrorCode {
    invalidArgument,
    notFound,
    unsupported,
    io,
    corruptData,
    resourceExhausted,
    cancelled,
    metal,
    internal,
};

struct Error {
    ErrorCode code{ErrorCode::internal};
    std::string message;
    std::string context;

    [[nodiscard]] std::string describe() const {
        return context.empty() ? message : message + " [" + context + "]";
    }
};

template <typename T> using Result = std::expected<T, Error>;

inline std::unexpected<Error> fail(ErrorCode code, std::string message, std::string context = {}) {
    return std::unexpected(Error{code, std::move(message), std::move(context)});
}

} // namespace aether
