add_library(AetherWorld STATIC
    src/EntityAssociation.cpp
    src/PersistentWorld.cpp
    src/SelectiveUpdate.cpp
    src/SemanticSceneGraph.cpp
    src/SpatialSemantics.cpp
    src/WorldArchive.cpp
    src/WorldEdit.cpp
    src/WorldModel.cpp
)
add_library(Aether::World ALIAS AetherWorld)

target_include_directories(AetherWorld PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(AetherWorld PUBLIC Aether::Core Aether::Scene PRIVATE simdjson::simdjson)

# simdjson is third-party code. Keep AETHER's warnings-as-errors policy for our own
# translation units without promoting dependency-header style/sign warnings to build failures.
get_target_property(AETHER_SIMDJSON_INCLUDE_DIRECTORIES
    simdjson::simdjson INTERFACE_INCLUDE_DIRECTORIES)
if(AETHER_SIMDJSON_INCLUDE_DIRECTORIES)
    target_include_directories(AetherWorld SYSTEM PRIVATE
        ${AETHER_SIMDJSON_INCLUDE_DIRECTORIES})
endif()

target_compile_features(AetherWorld PUBLIC cxx_std_23)
aether_configure_target(AetherWorld)
