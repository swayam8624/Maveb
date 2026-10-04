add_executable(maveb-gaussian-locality-bench
    main.cpp
)
target_link_libraries(maveb-gaussian-locality-bench PRIVATE Aether::WorldGaussian)
target_compile_features(maveb-gaussian-locality-bench PRIVATE cxx_std_23)
aether_configure_target(maveb-gaussian-locality-bench)
