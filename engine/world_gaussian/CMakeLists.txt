add_library(AetherWorldGaussian STATIC
    src/GaussianLocalUpdate.cpp
    src/GaussianOwnershipCodec.cpp
)
add_library(Aether::WorldGaussian ALIAS AetherWorldGaussian)

target_include_directories(AetherWorldGaussian PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherWorldGaussian PUBLIC Aether::Gaussian Aether::World)
target_compile_features(AetherWorldGaussian PUBLIC cxx_std_23)
aether_configure_target(AetherWorldGaussian)
