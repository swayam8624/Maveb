add_executable(AetherTests
    TestMain.cpp
)
target_link_libraries(AetherTests PRIVATE Aether::Canonical Aether::Core Aether::RenderGraph Aether::Scene Aether::Mesh Aether::Gaussian Aether::Hybrid Aether::Package Aether::Reconstruction)
target_compile_definitions(AetherTests PRIVATE
    AETHER_TEST_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
aether_configure_target(AetherTests)
add_test(NAME AetherTests COMMAND AetherTests)

add_executable(AetherOracleGeometryTests OracleGeometryTests.cpp)
target_link_libraries(AetherOracleGeometryTests PRIVATE Aether::Reconstruction)
aether_configure_target(AetherOracleGeometryTests)
add_test(NAME AetherOracleGeometryTests
    COMMAND AetherOracleGeometryTests --json-output
        "${PROJECT_BINARY_DIR}/test-artifacts/r1-oracle-geometry.json")

add_executable(AetherSparseTsdfTests SparseTsdfTests.cpp)
target_link_libraries(AetherSparseTsdfTests PRIVATE Aether::Reconstruction)
aether_configure_target(AetherSparseTsdfTests)
add_test(NAME AetherSparseTsdfTests
    COMMAND AetherSparseTsdfTests --json-output
        "${PROJECT_BINARY_DIR}/test-artifacts/r5-sparse-cpu-tsdf.json"
        --incremental-json-output
        "${PROJECT_BINARY_DIR}/test-artifacts/r5-incremental-meshing.json")
add_test(NAME AetherSparseTsdfEvidence
    COMMAND ${CMAKE_COMMAND} -E compare_files
        "${PROJECT_BINARY_DIR}/test-artifacts/r5-sparse-cpu-tsdf.json"
        "${PROJECT_SOURCE_DIR}/benchmarks/evidence/r5-sparse-cpu-m2-pro-2026-08-12.json")
set_tests_properties(AetherSparseTsdfEvidence PROPERTIES DEPENDS AetherSparseTsdfTests)
add_test(NAME AetherIncrementalSparseMeshingEvidence
    COMMAND ${CMAKE_COMMAND} -E compare_files
        "${PROJECT_BINARY_DIR}/test-artifacts/r5-incremental-meshing.json"
        "${PROJECT_SOURCE_DIR}/benchmarks/evidence/r5-incremental-meshing-m2-pro-2026-08-13.json")
set_tests_properties(AetherIncrementalSparseMeshingEvidence PROPERTIES
    DEPENDS AetherSparseTsdfTests)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME AetherProxyPythonTests
        COMMAND ${Python3_EXECUTABLE} -m unittest discover
            -s "${PROJECT_SOURCE_DIR}/tools/aether-proxy/tests" -v)
    set_tests_properties(AetherProxyPythonTests PROPERTIES
        ENVIRONMENT "PYTHONPATH=${PROJECT_SOURCE_DIR}/tools/aether-proxy/src")
endif()

if(TARGET AetherCapture)
    add_executable(AetherCaptureTests CaptureTests.cpp)
    target_link_libraries(AetherCaptureTests PRIVATE Aether::Capture
        "-framework CoreFoundation" "-framework CoreGraphics" "-framework ImageIO")
    aether_configure_target(AetherCaptureTests)
    add_test(NAME AetherCaptureTests COMMAND AetherCaptureTests)
endif()

if(TARGET aether-keyframes AND Python3_Interpreter_FOUND)
    add_test(NAME AetherKeyframeSelectorCli
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-keyframe-cli.py"
            $<TARGET_FILE:aether-keyframes>
            "${CMAKE_CURRENT_BINARY_DIR}/keyframe-selector-cli")
endif()

if(TARGET AetherMetal)
    add_executable(AetherSparseMetalTsdfTests SparseMetalTsdfTests.cpp)
    target_link_libraries(AetherSparseMetalTsdfTests PRIVATE Aether::Metal)
    target_compile_options(AetherSparseMetalTsdfTests PRIVATE -fblocks)
    set(AETHER_SPARSE_METAL_TEST_LIBRARY "")
    if(TARGET AetherShaders)
        set(AETHER_SPARSE_METAL_TEST_LIBRARY
            "${PROJECT_BINARY_DIR}/apps/AetherStudio/AetherShaders.metallib")
    endif()
    target_compile_definitions(AetherSparseMetalTsdfTests PRIVATE
        AETHER_TEST_SHADER_LIBRARY="${AETHER_SPARSE_METAL_TEST_LIBRARY}")
    aether_configure_target(AetherSparseMetalTsdfTests)
    if(TARGET AetherShaders)
        add_dependencies(AetherSparseMetalTsdfTests AetherShaders)
        add_test(NAME AetherSparseMetalTsdfTests
            COMMAND AetherSparseMetalTsdfTests --json-output
                "${PROJECT_BINARY_DIR}/test-artifacts/r5-sparse-metal-tsdf.json")
    endif()
endif()

if(TARGET AetherMetal AND TARGET AetherShaders)
    add_executable(AetherMetalTests MetalTests.cpp)
    target_link_libraries(AetherMetalTests PRIVATE Aether::Metal)
    target_compile_options(AetherMetalTests PRIVATE -fblocks)
    target_compile_definitions(AetherMetalTests PRIVATE
        AETHER_TEST_SHADER_LIBRARY="${PROJECT_BINARY_DIR}/apps/AetherStudio/AetherShaders.metallib"
        AETHER_TEST_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/triangle.gltf"
        AETHER_TEST_TEXTURED_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/textured-triangle.gltf"
        AETHER_TEST_INSTANCED_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/instanced-triangle.gltf"
        AETHER_TEST_ANIMATED_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/animated-triangle.gltf"
        AETHER_TEST_SKINNED_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/skinned-triangle.gltf"
        AETHER_TEST_MORPHED_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/morphed-triangle.gltf"
        AETHER_TEST_SHADOW_GLTF="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/shadow-casters.gltf"
        AETHER_TEST_PLY="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/gaussian-minimal.ply"
        AETHER_TEST_ARTIFACT_DIR="${PROJECT_BINARY_DIR}/test-artifacts/metal")
    if(TARGET AetherShaders)
        add_dependencies(AetherMetalTests AetherShaders)
    endif()
    aether_configure_target(AetherMetalTests)
    add_test(NAME AetherMetalTests COMMAND AetherMetalTests)

    add_executable(AetherSwiftTests
        SwiftDocumentTests.swift
        ${PROJECT_SOURCE_DIR}/apps/AetherStudio/Sources/AetherProjectDocument.swift
        ${PROJECT_SOURCE_DIR}/apps/AetherStudio/Sources/ReconstructionReport.swift
    )
    target_link_libraries(AetherSwiftTests PRIVATE "-framework SwiftUI" "-framework UniformTypeIdentifiers")
    add_test(NAME AetherSwiftTests COMMAND AetherSwiftTests)
endif()

if(TARGET aether-benchmark AND TARGET aether-pack)
    set(AETHER_BENCHMARK_TEST_SCENE "${CMAKE_CURRENT_BINARY_DIR}/benchmark-fixture.aether")
    add_test(NAME AetherBenchmarkFixturePack
        COMMAND $<TARGET_FILE:aether-pack>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/package-scene"
            --output "${AETHER_BENCHMARK_TEST_SCENE}" --json)
    set_tests_properties(AetherBenchmarkFixturePack PROPERTIES
        FIXTURES_SETUP AetherBenchmarkScene)
    add_test(NAME AetherBenchmarkSmoke
        COMMAND $<TARGET_FILE:aether-benchmark>
            "${AETHER_BENCHMARK_TEST_SCENE}"
            --camera-path "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/camera-path.json"
            --width 32 --height 32 --frames 2 --warmup 1
            --max-p95-ms 10000 --max-memory-bytes 1099511627776 --json)
    set_tests_properties(AetherBenchmarkSmoke PROPERTIES
        FIXTURES_REQUIRED AetherBenchmarkScene)
    add_test(NAME AetherBenchmark1080pFixtureSmoke
        COMMAND $<TARGET_FILE:aether-benchmark>
            "${AETHER_BENCHMARK_TEST_SCENE}"
            --camera-path "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/camera-path.json"
            --width 1920 --height 1080 --frames 10 --warmup 2
            --max-p95-ms 33.3 --max-memory-bytes 536870912 --json)
    set_tests_properties(AetherBenchmark1080pFixtureSmoke PROPERTIES
        FIXTURES_REQUIRED AetherBenchmarkScene)
    add_test(NAME AetherBenchmarkBudgetFailure
        COMMAND $<TARGET_FILE:aether-benchmark>
            "${AETHER_BENCHMARK_TEST_SCENE}"
            --camera-path "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/camera-path.json"
            --width 32 --height 32 --frames 1 --warmup 1
            --max-p95-ms 0.000001 --json)
    set_tests_properties(AetherBenchmarkBudgetFailure PROPERTIES
        FIXTURES_REQUIRED AetherBenchmarkScene WILL_FAIL TRUE)
endif()

if(TARGET aether-pack AND TARGET aether-inspect AND Python3_Interpreter_FOUND)
    add_test(NAME AetherCanonicalAssetCli
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-canonical-asset.py"
            $<TARGET_FILE:aether-pack>
            $<TARGET_FILE:aether-inspect>
            "${CMAKE_CURRENT_BINARY_DIR}/canonical-asset-cli")
endif()

if(TARGET aether-reconstruct)
    set(AETHER_RECONSTRUCTION_TEST_JOB "${CMAKE_CURRENT_BINARY_DIR}/reconstruction-job")
    add_test(NAME AetherReconstructionAdapter
        COMMAND $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            --output "${AETHER_RECONSTRUCTION_TEST_JOB}"
            --colmap "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap.zsh"
            --brush "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            --proxy "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh"
            --seed 42 --steps 10 --checkpoint-every 5 --json)
    add_test(NAME AetherReconstructionCoverageGate
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-coverage-gate.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${CMAKE_CURRENT_BINARY_DIR}/reconstruction-weak-job"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap-weak.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    add_test(NAME AetherReconstructionMultiModelSelection
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-multi-model-selection.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-multicamera"
            "${CMAKE_CURRENT_BINARY_DIR}/reconstruction-multi-model-job"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap-multi.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-multicamera/camera-groups.json")
    add_test(NAME AetherReconstructionFailedJobStatus
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-failed-job-status.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${CMAKE_CURRENT_BINARY_DIR}/reconstruction-failed-job"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap-fail.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    add_test(NAME AetherReconstructionVideoInputContract
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-video-input-contract.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${CMAKE_CURRENT_BINARY_DIR}/video-input-contract"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-multicamera"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-multicamera/camera-groups.json")
    add_test(NAME AetherReconstructionProxyResume
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-proxy-resume.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${AETHER_RECONSTRUCTION_TEST_JOB}"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    set_tests_properties(AetherReconstructionProxyResume PROPERTIES
        DEPENDS AetherReconstructionAdapter)
    add_test(NAME AetherBrushCheckpointRecovery
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-brush-checkpoint-recovery.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${AETHER_RECONSTRUCTION_TEST_JOB}"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    set_tests_properties(AetherBrushCheckpointRecovery PROPERTIES
        DEPENDS AetherReconstructionProxyResume)
    add_test(NAME AetherReconstructionResumeIdentity
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-resume-key.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${AETHER_RECONSTRUCTION_TEST_JOB}"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    set_tests_properties(AetherReconstructionResumeIdentity PROPERTIES
        DEPENDS AetherBrushCheckpointRecovery)
    add_test(NAME AetherReconstructionStrategyResumeIdentity
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-strategy-resume.zsh"
            $<TARGET_FILE:aether-reconstruct>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction"
            "${AETHER_RECONSTRUCTION_TEST_JOB}"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-colmap.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-brush.zsh"
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-proxy.zsh")
    set_tests_properties(AetherReconstructionStrategyResumeIdentity PROPERTIES
        DEPENDS AetherReconstructionResumeIdentity)
endif()

if(TARGET aether-fuse)
    add_test(NAME AetherOracleFusionCli
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-oracle-fusion.zsh"
            $<TARGET_FILE:aether-fuse>
            "${CMAKE_CURRENT_BINARY_DIR}/oracle-fusion")
endif()

if(TARGET maveb-photogrammetry AND Python3_Interpreter_FOUND)
    add_test(NAME MavebPhotogrammetryContract
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-photogrammetry-contract.py"
            $<TARGET_FILE:maveb-photogrammetry>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/mock-reconstruction/images"
            "${CMAKE_CURRENT_BINARY_DIR}/photogrammetry-contract.usdz")
endif()

if(CMAKE_Swift_COMPILER)
    add_executable(MavebCaptureJournalTests
        CaptureJournalTests.swift
        ${PROJECT_SOURCE_DIR}/apps/MavebCapture/Sources/CaptureManifest.swift
        ${PROJECT_SOURCE_DIR}/apps/MavebCapture/Sources/CaptureJournal.swift
    )
    set_target_properties(MavebCaptureJournalTests PROPERTIES Swift_LANGUAGE_VERSION 6)
    target_compile_options(MavebCaptureJournalTests PRIVATE
        "$<$<COMPILE_LANGUAGE:Swift>:-parse-as-library>")
    target_link_libraries(MavebCaptureJournalTests PRIVATE
        "-framework CryptoKit"
        "-framework Foundation")
    add_test(NAME MavebCaptureJournalTests COMMAND MavebCaptureJournalTests)

    add_executable(MavebCaptureAdmissionTests
        CaptureAdmissionTests.swift
        ${PROJECT_SOURCE_DIR}/apps/MavebCapture/Sources/CaptureAdmission.swift
    )
    set_target_properties(MavebCaptureAdmissionTests PROPERTIES Swift_LANGUAGE_VERSION 6)
    target_compile_options(MavebCaptureAdmissionTests PRIVATE
        "$<$<COMPILE_LANGUAGE:Swift>:-parse-as-library>")
    target_link_libraries(MavebCaptureAdmissionTests PRIVATE "-framework Foundation")
    add_test(NAME MavebCaptureAdmissionTests COMMAND MavebCaptureAdmissionTests)
endif()

if(TARGET maveb-align-sensors AND Python3_Interpreter_FOUND)
    add_test(NAME MavebSensorAlignmentCli
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-sensor-alignment.py"
            $<TARGET_FILE:maveb-align-sensors>
            "${CMAKE_CURRENT_BINARY_DIR}/sensor-alignment")
endif()



add_executable(MavebTextureBakerTests TextureBakerTests.cpp)
target_link_libraries(MavebTextureBakerTests PRIVATE Aether::Reconstruction)
aether_configure_target(MavebTextureBakerTests)
add_test(NAME MavebTextureBakerTests COMMAND MavebTextureBakerTests)


if(TARGET aether-export-glb AND Python3_Interpreter_FOUND)
    add_test(NAME AetherNativeGlbExport
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-native-glb.py"
            $<TARGET_FILE:aether-export-glb>
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
            "${CMAKE_CURRENT_BINARY_DIR}/native-glb")
endif()


if(TARGET maveb-texture-bake AND Python3_Interpreter_FOUND)
    add_test(NAME MavebTextureBakeCli
        COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/assert-texture-bake.py"
            $<TARGET_FILE:maveb-texture-bake>
            "${CMAKE_CURRENT_BINARY_DIR}/texture-bake")
endif()
