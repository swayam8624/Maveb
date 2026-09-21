add_library(AetherCBRC STATIC
    src/CapturedWorldRevisionGraph.cpp
)
add_library(Aether::CBRC ALIAS AetherCBRC)

target_include_directories(AetherCBRC PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherCBRC
    PUBLIC
        Aether::Revision
        Aether::Reconstruction
        Aether::World
)
target_compile_features(AetherCBRC PUBLIC cxx_std_23)
aether_configure_target(AetherCBRC)
