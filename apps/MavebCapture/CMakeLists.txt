cmake_minimum_required(VERSION 3.28)

project(MavebCapture LANGUAGES Swift)

if(NOT CMAKE_GENERATOR STREQUAL "Xcode")
    message(FATAL_ERROR "MavebCapture must be configured with the Xcode generator")
endif()

if(NOT CMAKE_SYSTEM_NAME STREQUAL "iOS")
    message(FATAL_ERROR "MavebCapture is an iPadOS application; configure with CMAKE_SYSTEM_NAME=iOS")
endif()

set(CMAKE_Swift_LANGUAGE_VERSION 6)

add_executable(MavebCapture MACOSX_BUNDLE
    Sources/CaptureManifest.swift
    Sources/CaptureJournal.swift
    Sources/CaptureAdmission.swift
    Sources/CaptureRecorder.swift
    Sources/CaptureController.swift
    Sources/CaptureView.swift
    Sources/MavebCaptureApp.swift
)

set_target_properties(MavebCapture PROPERTIES
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    XCODE_GENERATE_SCHEME TRUE
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "com.swayamsingal.maveb.capture"
    XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "2"
    XCODE_ATTRIBUTE_IPHONEOS_DEPLOYMENT_TARGET "17.0"
    XCODE_ATTRIBUTE_SWIFT_STRICT_CONCURRENCY "complete"
    XCODE_ATTRIBUTE_GENERATE_INFOPLIST_FILE "NO"
    XCODE_ATTRIBUTE_CODE_SIGN_STYLE "Automatic"
)

target_link_libraries(MavebCapture PRIVATE
    "-framework ARKit"
    "-framework AVFoundation"
    "-framework CoreVideo"
    "-framework CryptoKit"
    "-framework RealityKit"
    "-framework SwiftUI"
)
