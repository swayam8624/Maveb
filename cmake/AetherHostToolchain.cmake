# Host toolchain defaults for AETHER's CMake/Ninja builds.
#
# CMAKE_OSX_DEPLOYMENT_TARGET is sufficient for Clang-family languages, but
# Swift's Ninja driver can otherwise retain the toolchain's default target
# triple. Freeze both so the generated Mach-O load command matches the stated
# macOS 15.0 application requirement.

if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
    set(CMAKE_OSX_DEPLOYMENT_TARGET "15.0" CACHE STRING
        "Minimum macOS version supported by AETHER" FORCE)

    if(NOT CMAKE_Swift_COMPILER_TARGET)
        set(_aether_host_arch "${CMAKE_HOST_SYSTEM_PROCESSOR}")
        if(_aether_host_arch STREQUAL "")
            execute_process(
                COMMAND uname -m
                OUTPUT_VARIABLE _aether_host_arch
                OUTPUT_STRIP_TRAILING_WHITESPACE
                COMMAND_ERROR_IS_FATAL ANY)
        endif()

        if(NOT _aether_host_arch MATCHES "^(arm64|x86_64)$")
            message(FATAL_ERROR
                "Unsupported macOS host architecture for Swift: ${_aether_host_arch}")
        endif()

        set(CMAKE_Swift_COMPILER_TARGET
            "${_aether_host_arch}-apple-macosx${CMAKE_OSX_DEPLOYMENT_TARGET}"
            CACHE STRING "Swift target triple for host macOS builds" FORCE)
    endif()
endif()
