add_executable(aether-inspect main.cpp)
target_link_libraries(aether-inspect PRIVATE Aether::Canonical Aether::Core Aether::Package)
aether_configure_target(aether-inspect)
