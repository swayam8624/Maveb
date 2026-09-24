add_executable(maveb-cbrc-gaussian-oracle
    main.cpp
)
target_link_libraries(maveb-cbrc-gaussian-oracle PRIVATE
    Aether::Gaussian
    Aether::WorldGaussian
)
target_compile_features(maveb-cbrc-gaussian-oracle PRIVATE cxx_std_23)

if(APPLE)
    include(CompileMetal)
    target_link_libraries(maveb-cbrc-gaussian-oracle PRIVATE Aether::Metal)
    target_compile_options(maveb-cbrc-gaussian-oracle PRIVATE -fblocks)
    aether_add_metal_library(MavebCBRCOracleShaders "MavebCBRCOracleShaders.metallib"
        "${PROJECT_SOURCE_DIR}/shaders/gaussian.metal")
    if(TARGET MavebCBRCOracleShaders)
        add_dependencies(maveb-cbrc-gaussian-oracle MavebCBRCOracleShaders)
        target_compile_definitions(maveb-cbrc-gaussian-oracle PRIVATE
            AETHER_ORACLE_SHADER_LIBRARY="${MavebCBRCOracleShaders_OUTPUT}")
    endif()
endif()

aether_configure_target(maveb-cbrc-gaussian-oracle)
