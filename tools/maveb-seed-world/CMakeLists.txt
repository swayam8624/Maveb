add_executable(maveb-seed-world
    main.cpp
)

target_link_libraries(maveb-seed-world PRIVATE
    Aether::Gaussian
    Aether::Hybrid
    Aether::World
    Aether::WorldGaussian
)
target_compile_features(maveb-seed-world PRIVATE cxx_std_23)
aether_configure_target(maveb-seed-world)
