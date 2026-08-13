find_library(METAL_FRAMEWORK Metal REQUIRED)
find_library(METALKIT_FRAMEWORK MetalKit REQUIRED)
find_library(FOUNDATION_FRAMEWORK Foundation REQUIRED)
find_library(QUARTZCORE_FRAMEWORK QuartzCore REQUIRED)
find_library(IMAGEIO_FRAMEWORK ImageIO REQUIRED)
find_library(COREGRAPHICS_FRAMEWORK CoreGraphics REQUIRED)

add_library(AetherMetal STATIC
    src/FrameContext.cpp
    src/GaussianPipeline.cpp
    src/MetalSymbols.cpp
    src/Renderer.cpp
    src/ShaderABI.cpp
    src/SparseMetalTsdfVolume.cpp
)
add_library(Aether::Metal ALIAS AetherMetal)

target_include_directories(AetherMetal PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/shaders
)
target_include_directories(AetherMetal SYSTEM PUBLIC ${PROJECT_SOURCE_DIR}/external/metal-cpp)
target_link_libraries(AetherMetal
    PUBLIC Aether::Core Aether::RenderGraph Aether::Scene Aether::Mesh Aether::Gaussian Aether::Hybrid Aether::Package Aether::Reconstruction
    PRIVATE
        ${METAL_FRAMEWORK}
        ${METALKIT_FRAMEWORK}
        ${FOUNDATION_FRAMEWORK}
        ${QUARTZCORE_FRAMEWORK}
        ${IMAGEIO_FRAMEWORK}
        ${COREGRAPHICS_FRAMEWORK}
)
target_compile_options(AetherMetal PRIVATE -fblocks)
aether_configure_target(AetherMetal)
