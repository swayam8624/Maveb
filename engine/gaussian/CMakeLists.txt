add_library(AetherGaussian STATIC
    src/GaussianCodec.cpp
    src/GaussianUpdatePlan.cpp
    src/PlyLoader.cpp
    src/ReferenceRasterizer.cpp
)
add_library(Aether::Gaussian ALIAS AetherGaussian)

target_include_directories(AetherGaussian PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherGaussian PUBLIC Aether::Core)
target_compile_features(AetherGaussian PUBLIC cxx_std_23)
aether_configure_target(AetherGaussian)
