find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(MAVEB_BUILD_CANONICAL_SCENE_SCRIPT
    "${CMAKE_CURRENT_SOURCE_DIR}/maveb-build-canonical-scene.py")

add_custom_target(maveb-build-canonical-scene ALL
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MAVEB_BUILD_CANONICAL_SCENE_SCRIPT}"
        "${CMAKE_CURRENT_BINARY_DIR}/maveb-build-canonical-scene"
    COMMAND chmod +x "${CMAKE_CURRENT_BINARY_DIR}/maveb-build-canonical-scene"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/maveb-build-canonical-scene"
    VERBATIM)
