add_executable(maveb-texture-bake main.cpp)
target_link_libraries(maveb-texture-bake PRIVATE
    Aether::Core Aether::Hybrid Aether::Mesh Aether::Package Aether::Reconstruction
    simdjson::simdjson
    "-framework CoreFoundation" "-framework CoreGraphics" "-framework ImageIO")
target_include_directories(maveb-texture-bake SYSTEM PRIVATE ${simdjson_SOURCE_DIR}/include)
aether_configure_target(maveb-texture-bake)
