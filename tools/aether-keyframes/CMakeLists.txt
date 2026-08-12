add_executable(aether-keyframes main.cpp)
target_link_libraries(aether-keyframes PRIVATE Aether::Capture)
aether_configure_target(aether-keyframes)
