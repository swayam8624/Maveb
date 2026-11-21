// SOURCE STUDY NOTE:
// Scene-level data/operations feeding rendering. Compare Scene.hpp with Camera, Transform, Lighting and
// engine/metal/Renderer.cpp to trace the path from world description to GPU draw inputs.
// Follow docs/SOURCE_READING_ORDER.md for upstream/downstream files.

#include <aether/scene/Scene.hpp>

#include <utility>

namespace aether::scene {

// Reuse a freed slot or append a new node, but preserve its generation.
// Consumers keep an Entity{index,generation}; a recycled index alone is
// insufficient to identify an object from a previous lifetime.
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

// Reject stale handles, detach children to roots, advance the generation
// and recycle the index. Transform descendants may need recomputation when
// hierarchy ownership changes; inspect dirty propagation when extending.
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

// Full liveness check: bounds, alive flag, and matching generation.
// Every public mutator/accessor relies on this, not merely index range.
bool Scene::valid(Entity entity) const noexcept {
    return entity.index < nodes_.size() && nodes_[entity.index].alive &&
           nodes_[entity.index].generation == entity.generation;
}

// Reject invalid endpoints and cycles before changing parent links.
// Dirty the changed subtree so subsequent worldMatrix() requests compose
// transforms using the new hierarchy, not cached previous world matrices.
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

// Accept only finite transforms with nonzero scale, then dirty the
// descendant world-matrix cache. Renderer and world-edit consumers must
// distinguish local TRS from world-space transforms.
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

// Lazy world transform: create a recursion guard and call updateWorld()
// only when necessary. Parent transforms are evaluated before children;
// invalid entities return a typed Error instead of a default matrix.
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

// Walk the proposed parent's ancestors. If the child is encountered,
// adopting this parent would create a cycle and must be rejected.
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

// Invalidate world caches below a modified node; dirty flags ensure
// Renderer consumers recompute world transforms after parent/local edits.
void Scene::markDescendantsDirty(Entity parent) {
    for (std::size_t index = 0; index < nodes_.size(); ++index) {
        Node& node = nodes_[index];
        if (node.alive && node.parent == parent && !node.dirty) {
            node.dirty = true;
            markDescendantsDirty(Entity{static_cast<std::uint32_t>(index), node.generation});
        }
    }
}

// Recursively compute parentWorld * localMatrix and cache the result.
// The visiting guard detects unexpected cycles even if previous public
// validation was bypassed. This is read by engine/metal/Renderer.cpp.
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
