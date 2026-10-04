function(aether_add_metal_library target output_name)
    set(sources ${ARGN})
    execute_process(
        COMMAND xcrun -sdk macosx -find metal
        RESULT_VARIABLE metal_result
        OUTPUT_QUIET ERROR_QUIET
    )
    execute_process(
        COMMAND xcrun -sdk macosx -find metallib
        RESULT_VARIABLE metallib_result
        OUTPUT_QUIET ERROR_QUIET
    )

    if(NOT metal_result EQUAL 0 OR NOT metallib_result EQUAL 0)
        if(AETHER_REQUIRE_METAL_TOOLCHAIN)
            message(FATAL_ERROR
                "The Xcode Metal Toolchain is required. Run: "
                "xcodebuild -downloadComponent metalToolchain")
        endif()
        message(WARNING
            "Metal Toolchain is unavailable; ${target} will not be generated. "
            "Install it with: xcodebuild -downloadComponent metalToolchain")
        return()
    endif()

    set(air_files)
    foreach(source IN LISTS sources)
        get_filename_component(name "${source}" NAME_WE)
        set(air "${CMAKE_CURRENT_BINARY_DIR}/${name}.air")
        add_custom_command(
            OUTPUT "${air}"
            COMMAND xcrun -sdk macosx metal -std=metal3.1 -c "${source}" -o "${air}"
            DEPENDS "${source}"
            VERBATIM
        )
        list(APPEND air_files "${air}")
    endforeach()

    set(output "${CMAKE_CURRENT_BINARY_DIR}/${output_name}")
    add_custom_command(
        OUTPUT "${output}"
        COMMAND xcrun -sdk macosx metallib ${air_files} -o "${output}"
        DEPENDS ${air_files}
        VERBATIM
    )
    add_custom_target(${target} DEPENDS "${output}")
    set(${target}_OUTPUT "${output}" PARENT_SCOPE)
endfunction()
