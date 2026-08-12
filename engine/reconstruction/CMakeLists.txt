add_library(AetherReconstruction STATIC
    src/ReconstructionInput.cpp
    src/SparseModelValidator.cpp
    src/DenseTsdfVolume.cpp
    src/GeometryEvaluation.cpp
    src/RecordedProviders.cpp
    src/ColmapCameraRig.cpp
    src/SensorAlignment.cpp
)
add_library(Aether::Reconstruction ALIAS AetherReconstruction)
target_include_directories(AetherReconstruction PUBLIC include)
get_target_property(AETHER_RECONSTRUCTION_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
target_include_directories(AetherReconstruction SYSTEM PRIVATE
    ${AETHER_RECONSTRUCTION_SIMDJSON_INCLUDE_DIRECTORIES})
target_link_libraries(AetherReconstruction PUBLIC Aether::Core Aether::Capture Aether::Mesh
    PRIVATE simdjson::simdjson)
aether_configure_target(AetherReconstruction)
