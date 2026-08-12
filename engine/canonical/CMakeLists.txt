add_library(AetherCanonical STATIC
    src/CanonicalAsset.cpp
)
add_library(Aether::Canonical ALIAS AetherCanonical)

get_target_property(SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(AetherCanonical PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_include_directories(AetherCanonical SYSTEM PRIVATE
    ${SIMDJSON_INCLUDE_DIRECTORIES}
)
target_link_libraries(AetherCanonical PUBLIC Aether::Core Aether::Mesh PRIVATE simdjson::simdjson)
target_compile_features(AetherCanonical PUBLIC cxx_std_23)
aether_configure_target(AetherCanonical)
