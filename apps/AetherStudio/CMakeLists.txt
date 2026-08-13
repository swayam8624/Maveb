include(CompileMetal)

set(AETHER_STUDIO_SOURCES
    Sources/AetherProjectDocument.swift
    Sources/AetherStudioApp.swift
    Sources/ContentView.swift
    Sources/AetherViewport.swift
    Sources/ReconstructionReport.swift
    Sources/ReconstructionWorkspace.swift
    Sources/TrainingComparisonViewport.swift
    Bridge/AetherCaptureBridge.mm
    Bridge/AetherViewportBridge.mm
)

add_executable(AetherStudio MACOSX_BUNDLE ${AETHER_STUDIO_SOURCES})
target_link_libraries(AetherStudio PRIVATE Aether::Metal Aether::Capture
    "-framework AppKit" "-framework Metal" "-framework MetalKit" "-framework SwiftUI")
target_include_directories(AetherStudio PRIVATE Bridge)

set(bridging_header "${CMAKE_CURRENT_SOURCE_DIR}/Bridge/AetherStudio-Bridging-Header.h")
target_compile_options(AetherStudio PRIVATE
    "$<$<COMPILE_LANGUAGE:Swift>:-import-objc-header;${bridging_header}>"
    "$<$<COMPILE_LANGUAGE:OBJCXX>:-fobjc-arc>"
)

set_target_properties(AetherStudio PROPERTIES
    MACOSX_BUNDLE_BUNDLE_NAME "AETHER"
    MACOSX_BUNDLE_GUI_IDENTIFIER "com.swayamsingal.aether"
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "com.swayamsingal.aether"
    XCODE_ATTRIBUTE_SWIFT_OBJC_BRIDGING_HEADER "${bridging_header}"
    XCODE_ATTRIBUTE_MACOSX_DEPLOYMENT_TARGET "15.0"
)

aether_add_metal_library(AetherShaders "AetherShaders.metallib"
    "${PROJECT_SOURCE_DIR}/shaders/viewport.metal"
    "${PROJECT_SOURCE_DIR}/shaders/pbr.metal"
    "${PROJECT_SOURCE_DIR}/shaders/gizmo.metal"
    "${PROJECT_SOURCE_DIR}/shaders/proxy.metal"
    "${PROJECT_SOURCE_DIR}/shaders/shadow.metal"
    "${PROJECT_SOURCE_DIR}/shaders/tsdf.metal"
    "${PROJECT_SOURCE_DIR}/shaders/gaussian.metal")
if(TARGET AetherShaders)
    add_dependencies(AetherStudio AetherShaders)
    target_sources(AetherStudio PRIVATE "${AetherShaders_OUTPUT}")
    set_source_files_properties("${AetherShaders_OUTPUT}" PROPERTIES
        MACOSX_PACKAGE_LOCATION Resources
        GENERATED TRUE)
endif()

if(TARGET aether-reconstruct)
    add_dependencies(AetherStudio aether-reconstruct)
    add_custom_command(TARGET AetherStudio POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory
            "$<TARGET_BUNDLE_DIR:AetherStudio>/Contents/Helpers"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:aether-reconstruct>"
            "$<TARGET_BUNDLE_DIR:AetherStudio>/Contents/Helpers/aether-reconstruct"
        VERBATIM)
endif()
