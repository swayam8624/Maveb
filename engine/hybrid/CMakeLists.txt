add_library(AetherHybrid STATIC
    src/ProxyMeshCodec.cpp
    src/ProxyPlyLoader.cpp
)
add_library(Aether::Hybrid ALIAS AetherHybrid)
target_include_directories(AetherHybrid PUBLIC include)
target_link_libraries(AetherHybrid PUBLIC Aether::Core)
aether_configure_target(AetherHybrid)
