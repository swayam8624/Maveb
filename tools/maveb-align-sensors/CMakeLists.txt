add_executable(maveb-align-sensors main.cpp)
target_link_libraries(maveb-align-sensors PRIVATE Aether::Capture Aether::Package
    Aether::Reconstruction simdjson::simdjson)
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(maveb-align-sensors SYSTEM PRIVATE
    ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})
aether_configure_target(maveb-align-sensors)
