#pragma once

#include <aether/core/Error.hpp>

#include <cstdint>
#include <functional>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace aether::rendergraph {

struct ResourceHandle {
    std::uint32_t index{std::numeric_limits<std::uint32_t>::max()};
    std::uint32_t generation{};
    auto operator<=>(const ResourceHandle&) const = default;
};

struct ResourceLifetime {
    ResourceHandle resource;
    std::uint32_t firstPass{};
    std::uint32_t lastPass{};
};

struct CompiledPass {
    std::string name;
    std::function<void()> execute;
};

class CompiledGraph final {
  public:
    [[nodiscard]] const std::vector<CompiledPass>& passes() const noexcept {
        return passes_;
    }
    [[nodiscard]] const std::vector<ResourceLifetime>& lifetimes() const noexcept {
        return lifetimes_;
    }
    [[nodiscard]] const std::string& dot() const noexcept {
        return dot_;
    }
    void execute() const;

  private:
    friend class RenderGraph;
    std::vector<CompiledPass> passes_;
    std::vector<ResourceLifetime> lifetimes_;
    std::string dot_;
};

class RenderGraph final {
  public:
    ResourceHandle createResource(std::string name, bool transient = true);
    Result<void> markOutput(ResourceHandle resource);

    Result<void> addPass(std::string name, std::vector<ResourceHandle> reads,
                         std::vector<ResourceHandle> writes, std::function<void()> execute,
                         bool sideEffect = false);

    [[nodiscard]] Result<CompiledGraph> compile() const;
    void reset();

  private:
    struct Resource {
        std::string name;
        std::uint32_t generation{1};
        bool transient{true};
        bool output{false};
    };

    struct Pass {
        std::string name;
        std::vector<ResourceHandle> reads;
        std::vector<ResourceHandle> writes;
        std::function<void()> execute;
        bool sideEffect{false};
    };

    [[nodiscard]] bool valid(ResourceHandle handle) const noexcept;

    std::vector<Resource> resources_;
    std::vector<Pass> passes_;
};

} // namespace aether::rendergraph
