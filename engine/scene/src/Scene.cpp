#include <aether/scene/Scene.hpp>

#include <utility>

namespace aether::scene {

Entity Scene::createEntity(std::string name) {
    std::uint32_t index = 0;
    if (freeList_.empty()) {
        index = static_cast<std::uint32_t>(nodes_.size());
        nodes_.emplace_back();
    } else {
        index = freeList_.back();
        freeList_.pop_back();
    }
    Node& node = nodes_[index];
    node.alive = true;
    node.dirty = true;
    node.name = std::move(name);
    node.local = Transform::identity();
    node.parent.reset();
    node.world = matrix_identity_float4x4;
    ++livingCount_;
    return Entity{index, node.generation};
}

Result<void> Scene::destroyEntity(Entity entity) {
    if (!valid(entity)) {
        return fail(ErrorCode::invalidArgument, "Cannot destroy an invalid scene entity");
    }
    for (Node& node : nodes_) {
        if (node.alive && node.parent == entity) {
            node.parent.reset();
            node.dirty = true;
        }
    }
    Node& node = nodes_[entity.index];
    node.alive = false;
    node.name.clear();
    node.parent.reset();
    ++node.generation;
    freeList_.push_back(entity.index);
    --livingCount_;
    return {};
}

bool Scene::valid(Entity entity) const noexcept {
    return entity.index < nodes_.size() && nodes_[entity.index].alive &&
           nodes_[entity.index].generation == entity.generation;
}

Result<void> Scene::setParent(Entity child, std::optional<Entity> parent) {
    if (!valid(child) || (parent && !valid(*parent))) {
        return fail(ErrorCode::invalidArgument, "Parenting requires valid scene entities");
    }
    if (parent && (*parent == child || wouldCreateCycle(child, *parent))) {
        return fail(ErrorCode::invalidArgument, "Scene parenting would create a cycle");
    }
    nodes_[child.index].parent = parent;
    nodes_[child.index].dirty = true;
    markDescendantsDirty(child);
    return {};
}

Result<void> Scene::setLocalTransform(Entity entity, const Transform& transform) {
    if (!valid(entity) || !isFinite(transform) || !hasNonZeroScale(transform)) {
        return fail(ErrorCode::invalidArgument,
                    "Entity transform requires a valid entity, finite values, and non-zero scale");
    }
    nodes_[entity.index].local = transform;
    nodes_[entity.index].dirty = true;
    markDescendantsDirty(entity);
    return {};
}

Result<Transform> Scene::localTransform(Entity entity) const {
    if (!valid(entity)) {
        return fail(ErrorCode::invalidArgument, "Invalid entity transform request");
    }
    return nodes_[entity.index].local;
}

Result<simd_float4x4> Scene::worldMatrix(Entity entity) {
    if (!valid(entity)) {
        return fail(ErrorCode::invalidArgument, "Invalid entity world-matrix request");
    }
    std::vector<bool> visiting(nodes_.size(), false);
    return updateWorld(entity, visiting);
}

Result<std::string> Scene::name(Entity entity) const {
    if (!valid(entity)) {
        return fail(ErrorCode::invalidArgument, "Invalid entity name request");
    }
    return nodes_[entity.index].name;
}

bool Scene::wouldCreateCycle(Entity child, Entity parent) const {
    std::optional<Entity> cursor = parent;
    while (cursor && valid(*cursor)) {
        if (*cursor == child) {
            return true;
        }
        cursor = nodes_[cursor->index].parent;
    }
    return false;
}

void Scene::markDescendantsDirty(Entity parent) {
    for (std::size_t index = 0; index < nodes_.size(); ++index) {
        Node& node = nodes_[index];
        if (node.alive && node.parent == parent && !node.dirty) {
            node.dirty = true;
            markDescendantsDirty(Entity{static_cast<std::uint32_t>(index), node.generation});
        }
    }
}

Result<simd_float4x4> Scene::updateWorld(Entity entity, std::vector<bool>& visiting) {
    Node& node = nodes_[entity.index];
    if (!node.dirty) {
        return node.world;
    }
    if (visiting[entity.index]) {
        return fail(ErrorCode::internal, "Cycle detected while updating scene transforms");
    }
    visiting[entity.index] = true;
    simd_float4x4 parentWorld = matrix_identity_float4x4;
    if (node.parent) {
        auto result = updateWorld(*node.parent, visiting);
        if (!result) {
            return std::unexpected(result.error());
        }
        parentWorld = *result;
    }
    node.world = simd_mul(parentWorld, node.local.matrix());
    node.dirty = false;
    visiting[entity.index] = false;
    return node.world;
}

} // namespace aether::scene
