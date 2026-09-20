add_executable(maveb-update-locality-probe main.cpp)
target_link_libraries(maveb-update-locality-probe PRIVATE Aether::WorldGaussian)
aether_configure_target(maveb-update-locality-probe)
