include(CompileMetal)

add_executable(aether-benchmark main.cpp)
target_link_libraries(aether-benchmark PRIVATE
    Aether::Core Aether::Gaussian Aether::Metal Aether::Package Aether::Scene)
target_compile_options(aether-benchmark PRIVATE -fblocks)
aether_configure_target(aether-benchmark)

aether_add_metal_library(AetherBenchmarkShaders "AetherBenchmarkShaders.metallib"
    "${PROJECT_SOURCE_DIR}/shaders/gaussian.metal")
if(TARGET AetherBenchmarkShaders)
    add_dependencies(aether-benchmark AetherBenchmarkShaders)
    target_compile_definitions(aether-benchmark PRIVATE
        AETHER_BENCHMARK_SHADER_LIBRARY="${AetherBenchmarkShaders_OUTPUT}")
endif()
