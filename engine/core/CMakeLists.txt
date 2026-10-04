add_library(AetherCore STATIC
    src/Diagnostics.cpp
    src/JobSystem.cpp
    src/Log.cpp
    src/Profiler.cpp
    src/ResourceLocator.cpp
)
add_library(Aether::Core ALIAS AetherCore)

target_include_directories(AetherCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)
target_compile_features(AetherCore PUBLIC cxx_std_23)
aether_configure_target(AetherCore)
