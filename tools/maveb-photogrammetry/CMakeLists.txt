add_executable(maveb-photogrammetry main.swift)
set_target_properties(maveb-photogrammetry PROPERTIES
    Swift_LANGUAGE_VERSION 6
    MACOSX_DEPLOYMENT_TARGET 15.0
)
target_link_libraries(maveb-photogrammetry PRIVATE
    "-framework CryptoKit"
    "-framework RealityKit"
)
target_compile_options(maveb-photogrammetry PRIVATE
    "$<$<COMPILE_LANGUAGE:Swift>:-parse-as-library>"
)
