add_library(AetherScene STATIC
    src/Camera.cpp
    src/CameraPath.cpp
    src/CameraController.cpp
    src/Lighting.cpp
    src/ImageBasedLighting.cpp
    src/Scene.cpp
    src/TemporalInvalidation.cpp
    src/TemporalRevisionCertificate.cpp
    src/Shadows.cpp
    src/Transform.cpp
)
add_library(Aether::Scene ALIAS AetherScene)

target_include_directories(AetherScene PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(AetherScene SYSTEM PRIVATE ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})
target_link_libraries(AetherScene PUBLIC Aether::Core PRIVATE simdjson::simdjson)
target_compile_features(AetherScene PUBLIC cxx_std_23)
aether_configure_target(AetherScene)
