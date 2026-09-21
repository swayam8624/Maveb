add_executable(maveb-seed-trained-3dgs-world
    main.cpp
)

target_link_libraries(maveb-seed-trained-3dgs-world PRIVATE
    Aether::Gaussian
    Aether::World
    Aether::WorldGaussian
)
target_compile_features(maveb-seed-trained-3dgs-world PRIVATE cxx_std_23)
aether_configure_target(maveb-seed-trained-3dgs-world)
