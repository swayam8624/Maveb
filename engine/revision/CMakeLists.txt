add_library(AetherRevision STATIC
    src/RevisionPlanner.cpp
    src/RevisionCertificateJson.cpp
)
add_library(Aether::Revision ALIAS AetherRevision)

target_include_directories(AetherRevision PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherRevision PUBLIC Aether::Core)
target_compile_features(AetherRevision PUBLIC cxx_std_23)
aether_configure_target(AetherRevision)
