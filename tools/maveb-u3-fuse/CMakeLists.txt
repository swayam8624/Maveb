add_executable(maveb-u3-fuse main.cpp)
target_link_libraries(maveb-u3-fuse PRIVATE
    Aether::Core Aether::Capture Aether::Reconstruction Aether::Mesh simdjson::simdjson)
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(maveb-u3-fuse SYSTEM PRIVATE
    ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})
aether_configure_target(maveb-u3-fuse)
