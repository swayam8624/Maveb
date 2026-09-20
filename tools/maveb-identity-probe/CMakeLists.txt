add_executable(maveb-identity-probe main.cpp)
target_link_libraries(maveb-identity-probe PRIVATE Aether::World)
aether_configure_target(maveb-identity-probe)
