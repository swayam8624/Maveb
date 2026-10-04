add_library(AetherPackage STATIC
    src/Package.cpp
    src/Sha256.cpp
)
add_library(Aether::Package ALIAS AetherPackage)

target_include_directories(AetherPackage PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherPackage PUBLIC Aether::Core PRIVATE libzstd_static)
target_compile_features(AetherPackage PUBLIC cxx_std_23)
aether_configure_target(AetherPackage)
