add_library(AetherWorldAdapters STATIC
    src/CanonicalObservationAdapter.cpp
)
add_library(Aether::WorldAdapters ALIAS AetherWorldAdapters)

target_include_directories(AetherWorldAdapters PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherWorldAdapters PUBLIC
    Aether::Canonical
    Aether::Mesh
    Aether::World
)
target_compile_features(AetherWorldAdapters PUBLIC cxx_std_23)
aether_configure_target(AetherWorldAdapters)
