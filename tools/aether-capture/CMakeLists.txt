add_executable(aether-capture main.cpp)
target_link_libraries(aether-capture PRIVATE Aether::Capture)
aether_configure_target(aether-capture)
