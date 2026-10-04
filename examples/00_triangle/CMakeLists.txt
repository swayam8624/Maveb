add_executable(AetherTriangle MACOSX_BUNDLE
    main.cpp
    control/app_delegate.cpp
    control/view_delegate.cpp
    view/renderer.cpp
    view/mesh_factory.cpp
)
target_include_directories(AetherTriangle SYSTEM PRIVATE
    ${PROJECT_SOURCE_DIR}/external/metal-cpp
)
target_link_libraries(AetherTriangle PRIVATE
    "-framework Metal" "-framework MetalKit" "-framework AppKit"
    "-framework Foundation" "-framework QuartzCore")
target_compile_definitions(AetherTriangle PRIVATE
    AETHER_TUTORIAL_SHADER_DIR="${CMAKE_CURRENT_SOURCE_DIR}/shaders")
aether_configure_target(AetherTriangle)
