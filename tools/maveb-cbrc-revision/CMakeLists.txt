add_executable(maveb-cbrc-revision
    main.cpp
)
target_link_libraries(maveb-cbrc-revision PRIVATE
    Aether::Gaussian
    Aether::World
    Aether::WorldGaussian
    Aether::Revision
)
target_compile_features(maveb-cbrc-revision PRIVATE cxx_std_23)
aether_configure_target(maveb-cbrc-revision)
