#include <aether/rendergraph/RenderGraph.hpp>

#include <algorithm>
#include <deque>
#include <optional>
#include <sstream>

namespace aether::rendergraph {

void CompiledGraph::execute() const {
    for (const auto& pass : passes_) {
        if (pass.execute) {
            pass.execute();
        }
    }
}

ResourceHandle RenderGraph::createResource(std::string name, bool transient) {
    const auto index = static_cast<std::uint32_t>(resources_.size());
    resources_.push_back(Resource{std::move(name), 1, transient, false});
    return ResourceHandle{index, 1};
}

Result<void> RenderGraph::markOutput(ResourceHandle resource) {
    if (!valid(resource)) {
        return fail(ErrorCode::invalidArgument, "Cannot export an invalid render-graph resource");
    }
    resources_[resource.index].output = true;
    return {};
}

Result<void> RenderGraph::addPass(std::string name, std::vector<ResourceHandle> reads,
                                  std::vector<ResourceHandle> writes, std::function<void()> execute,
                                  bool sideEffect) {
    if (name.empty()) {
        return fail(ErrorCode::invalidArgument, "Render-graph pass name cannot be empty");
    }
    for (const ResourceHandle handle : reads) {
        if (!valid(handle)) {
            return fail(ErrorCode::invalidArgument, "Pass reads an invalid resource", name);
        }
    }
    for (const ResourceHandle handle : writes) {
        if (!valid(handle)) {
            return fail(ErrorCode::invalidArgument, "Pass writes an invalid resource", name);
        }
    }
    passes_.push_back(
        Pass{std::move(name), std::move(reads), std::move(writes), std::move(execute), sideEffect});
    return {};
}

Result<CompiledGraph> RenderGraph::compile() const {
    const std::size_t passCount = passes_.size();
    std::vector<std::vector<std::size_t>> dependencies(passCount);
    std::vector<std::vector<std::size_t>> dependants(passCount);
    std::vector<std::optional<std::size_t>> lastWriter(resources_.size());
    std::vector<std::vector<std::size_t>> readers(resources_.size());

    const auto addDependency = [&](std::size_t pass, std::size_t dependency) {
        auto& values = dependencies[pass];
        if (std::find(values.begin(), values.end(), dependency) == values.end()) {
            values.push_back(dependency);
            dependants[dependency].push_back(pass);
        }
    };

    for (std::size_t passIndex = 0; passIndex < passCount; ++passIndex) {
        const Pass& pass = passes_[passIndex];
        for (const ResourceHandle handle : pass.reads) {
            if (lastWriter[handle.index]) {
                addDependency(passIndex, *lastWriter[handle.index]);
            }
            readers[handle.index].push_back(passIndex);
        }
        for (const ResourceHandle handle : pass.writes) {
            if (lastWriter[handle.index]) {
                addDependency(passIndex, *lastWriter[handle.index]);
            }
            for (const std::size_t reader : readers[handle.index]) {
                if (reader != passIndex) {
                    addDependency(passIndex, reader);
                }
            }
            readers[handle.index].clear();
            lastWriter[handle.index] = passIndex;
        }
    }

    std::vector<bool> live(passCount, false);
    std::vector<std::size_t> work;
    for (std::size_t passIndex = 0; passIndex < passCount; ++passIndex) {
        bool required = passes_[passIndex].sideEffect;
        for (const ResourceHandle handle : passes_[passIndex].writes) {
            required = required || resources_[handle.index].output;
        }
        if (required) {
            live[passIndex] = true;
            work.push_back(passIndex);
        }
    }
    while (!work.empty()) {
        const std::size_t pass = work.back();
        work.pop_back();
        for (const std::size_t dependency : dependencies[pass]) {
            if (!live[dependency]) {
                live[dependency] = true;
                work.push_back(dependency);
            }
        }
    }

    std::vector<std::size_t> indegree(passCount, 0);
    std::deque<std::size_t> ready;
    std::size_t liveCount = 0;
    for (std::size_t pass = 0; pass < passCount; ++pass) {
        if (!live[pass]) {
            continue;
        }
        ++liveCount;
        indegree[pass] = static_cast<std::size_t>(
            std::count_if(dependencies[pass].begin(), dependencies[pass].end(),
                          [&](std::size_t dependency) { return live[dependency]; }));
        if (indegree[pass] == 0) {
            ready.push_back(pass);
        }
    }

    std::vector<std::size_t> order;
    while (!ready.empty()) {
        const std::size_t pass = ready.front();
        ready.pop_front();
        order.push_back(pass);
        for (const std::size_t dependant : dependants[pass]) {
            if (live[dependant] && --indegree[dependant] == 0) {
                ready.push_back(dependant);
            }
        }
    }
    if (order.size() != liveCount) {
        return fail(ErrorCode::invalidArgument, "Render graph contains a dependency cycle");
    }

    CompiledGraph compiled;
    std::vector<std::optional<std::uint32_t>> first(resources_.size());
    std::vector<std::optional<std::uint32_t>> last(resources_.size());
    for (std::size_t position = 0; position < order.size(); ++position) {
        const Pass& pass = passes_[order[position]];
        compiled.passes_.push_back(CompiledPass{pass.name, pass.execute});
        const auto note = [&](ResourceHandle handle) {
            const auto location = static_cast<std::uint32_t>(position);
            if (!first[handle.index]) {
                first[handle.index] = location;
            }
            last[handle.index] = location;
        };
        for (const ResourceHandle handle : pass.reads)
            note(handle);
        for (const ResourceHandle handle : pass.writes)
            note(handle);
    }
    for (std::size_t resource = 0; resource < resources_.size(); ++resource) {
        if (first[resource]) {
            compiled.lifetimes_.push_back(
                ResourceLifetime{ResourceHandle{static_cast<std::uint32_t>(resource),
                                                resources_[resource].generation},
                                 *first[resource], *last[resource]});
        }
    }

    std::ostringstream dot;
    dot << "digraph AetherRenderGraph {\n";
    for (std::size_t pass = 0; pass < passCount; ++pass) {
        if (live[pass])
            dot << "  p" << pass << " [label=\"" << passes_[pass].name << "\"];\n";
    }
    for (std::size_t pass = 0; pass < passCount; ++pass) {
        if (!live[pass])
            continue;
        for (const std::size_t dependency : dependencies[pass]) {
            if (live[dependency])
                dot << "  p" << dependency << " -> p" << pass << ";\n";
        }
    }
    dot << "}\n";
    compiled.dot_ = dot.str();
    return compiled;
}

void RenderGraph::reset() {
    resources_.clear();
    passes_.clear();
}

bool RenderGraph::valid(ResourceHandle handle) const noexcept {
    return handle.index < resources_.size() &&
           resources_[handle.index].generation == handle.generation;
}

} // namespace aether::rendergraph
