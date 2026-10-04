add_library(AetherRenderGraph STATIC src/RenderGraph.cpp)
add_library(Aether::RenderGraph ALIAS AetherRenderGraph)

target_include_directories(AetherRenderGraph PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherRenderGraph PUBLIC Aether::Core)
target_compile_features(AetherRenderGraph PUBLIC cxx_std_23)
aether_configure_target(AetherRenderGraph)
