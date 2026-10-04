add_executable(aether-fuse main.cpp)
target_link_libraries(aether-fuse PRIVATE
    Aether::Core Aether::Capture Aether::Reconstruction Aether::Mesh)
aether_configure_target(aether-fuse)
