add_library(AetherCapture STATIC 
    src/CaptureValidator.cpp
    src/KeyframeSelector.cpp
    src/CapturePacket.cpp
    src/RecordedSequenceSource.cpp
    calibration/CalibrationLoader.cpp
    src/AVFoundationFrameSource.mm
)
add_library(Aether::Capture ALIAS AetherCapture)

set_source_files_properties(src/AVFoundationFrameSource.mm PROPERTIES
    COMPILE_OPTIONS "-fobjc-arc"
)

target_include_directories(AetherCapture PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>)
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(AetherCapture SYSTEM PRIVATE ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})

target_link_libraries(AetherCapture PUBLIC Aether::Core
    PRIVATE Aether::Package
    PRIVATE "-framework CoreFoundation" "-framework CoreGraphics" "-framework ImageIO" "-framework AVFoundation" "-framework CoreMedia" "-framework CoreVideo" simdjson::simdjson)
target_compile_features(AetherCapture PUBLIC cxx_std_23)
aether_configure_target(AetherCapture)
