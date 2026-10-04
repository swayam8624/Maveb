add_executable(maveb-cbrc-work-bench
    main.cpp
)

target_link_libraries(maveb-cbrc-work-bench PRIVATE
    Aether::Gaussian
)
target_compile_features(maveb-cbrc-work-bench PRIVATE cxx_std_23)
aether_configure_target(maveb-cbrc-work-bench)
