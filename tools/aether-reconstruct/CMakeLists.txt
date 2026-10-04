add_executable(aether-reconstruct main.cpp)
target_link_libraries(aether-reconstruct PRIVATE Aether::Core Aether::Gaussian Aether::Package Aether::Reconstruction)
aether_configure_target(aether-reconstruct)
