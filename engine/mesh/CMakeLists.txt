add_library(AetherMesh STATIC
    src/Animation.cpp
    src/GltfExporter.cpp
    src/GltfLoader.cpp
    src/PlyExporter.cpp
)
add_library(Aether::Mesh ALIAS AetherMesh)

target_include_directories(AetherMesh PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/shaders>
)
target_include_directories(AetherMesh SYSTEM PRIVATE ${fastgltf_SOURCE_DIR}/include)
target_link_libraries(AetherMesh PUBLIC Aether::Core Aether::Scene PRIVATE fastgltf::fastgltf)
target_compile_features(AetherMesh PUBLIC cxx_std_23)
aether_configure_target(AetherMesh)
