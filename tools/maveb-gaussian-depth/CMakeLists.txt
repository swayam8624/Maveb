add_executable(maveb-gaussian-depth main.cpp)
target_link_libraries(maveb-gaussian-depth PRIVATE
    Aether::Core Aether::Gaussian simdjson::simdjson)
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(maveb-gaussian-depth SYSTEM PRIVATE
    ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})
aether_configure_target(maveb-gaussian-depth)
