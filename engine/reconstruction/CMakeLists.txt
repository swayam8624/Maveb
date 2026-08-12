add_library(AetherReconstruction STATIC
    src/SparseModelValidator.cpp
    src/DenseTsdfVolume.cpp
    src/GeometryEvaluation.cpp
    src/RecordedProviders.cpp
    src/TextureBaker.cpp
)
add_library(Aether::Reconstruction ALIAS AetherReconstruction)
target_include_directories(AetherReconstruction PUBLIC include)
target_link_libraries(AetherReconstruction PUBLIC Aether::Core Aether::Capture Aether::Mesh)
aether_configure_target(AetherReconstruction)
