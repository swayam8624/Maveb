add_executable(aether-export-glb main.cpp)
target_link_libraries(aether-export-glb PRIVATE Aether::Core Aether::Mesh Aether::Package)
aether_configure_target(aether-export-glb)
