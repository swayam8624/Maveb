add_library(AetherWorld STATIC
    src/EntityAssociation.cpp
    src/PersistentWorld.cpp
    src/SelectiveUpdate.cpp
    src/WorldArchive.cpp
    src/WorldEdit.cpp
    src/WorldModel.cpp
)
add_library(Aether::World ALIAS AetherWorld)

target_include_directories(AetherWorld PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherWorld PUBLIC Aether::Core Aether::Scene PRIVATE simdjson::simdjson)
target_compile_features(AetherWorld PUBLIC cxx_std_23)
aether_configure_target(AetherWorld)
