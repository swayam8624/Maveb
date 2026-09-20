add_executable(maveb-cbrc-gaussian-oracle
    main.cpp
)
target_link_libraries(maveb-cbrc-gaussian-oracle PRIVATE
    Aether::Gaussian
    Aether::WorldGaussian
)
target_compile_features(maveb-cbrc-gaussian-oracle PRIVATE cxx_std_23)
aether_configure_target(maveb-cbrc-gaussian-oracle)
