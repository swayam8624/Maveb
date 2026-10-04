#pragma once

#include <aether/core/Error.hpp>
#include <aether/scene/Transform.hpp>

#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace aether::scene {

struct Entity {
    std::uint32_t index{std::numeric_limits<std::uint32_t>::max()};
    std::uint32_t generation{};
    auto operator<=>(const Entity&) const = default;
};

class Scene final {
  public:
    [[nodiscard]] Entity createEntity(std::string name);
    [[nodiscard]] Result<void> destroyEntity(Entity entity);
    [[nodiscard]] bool valid(Entity entity) const noexcept;

    [[nodiscard]] Result<void> setParent(Entity child, std::optional<Entity> parent);
    [[nodiscard]] Result<void> setLocalTransform(Entity entity, const Transform& transform);
    [[nodiscard]] Result<Transform> localTransform(Entity entity) const;
    [[nodiscard]] Result<simd_float4x4> worldMatrix(Entity entity);
    [[nodiscard]] Result<std::string> name(Entity entity) const;
    [[nodiscard]] std::size_t entityCount() const noexcept {
        return livingCount_;
    }

  private:
    struct Node {
        std::uint32_t generation{1};
        bool alive{};
        bool dirty{true};
        std::string name;
        Transform local;
        std::optional<Entity> parent;
        simd_float4x4 world = matrix_identity_float4x4;
    };

    [[nodiscard]] bool wouldCreateCycle(Entity child, Entity parent) const;
    void markDescendantsDirty(Entity parent);
    [[nodiscard]] Result<simd_float4x4> updateWorld(Entity entity, std::vector<bool>& visiting);

    std::vector<Node> nodes_;
    std::vector<std::uint32_t> freeList_;
    std::size_t livingCount_{};
};

} // namespace aether::scene
