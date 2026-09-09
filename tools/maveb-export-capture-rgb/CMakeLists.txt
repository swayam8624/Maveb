add_executable(maveb-export-capture-rgb main.cpp)
target_link_libraries(maveb-export-capture-rgb PRIVATE
    Aether::Capture
    Aether::Package
    "-framework CoreFoundation"
    "-framework CoreGraphics"
    "-framework ImageIO")
aether_configure_target(maveb-export-capture-rgb)
