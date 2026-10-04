import Foundation

@main
enum SwiftDocumentTests {
    static func main() throws {
        let state = AetherProjectState(
            displayName: "Fixture",
            scenePath: "Scenes/fixture.aether",
            dynamicMeshPath: "Assets/sphere.glb",
            selectedWorkspace: "Lighting",
            entityTransformOverrides: ["1": AetherTransformOverride(values: [1, 2, 3, 0, 0, 0, 1,
                                                                              -1, 2, 3])],
            materialOverrides: ["1": AetherMaterialOverride(values: [0.8, 0.2, 0.1, 1, 0, 0, 0,
                                                                       0.4, 0.7, 1, 1, 0.5])],
            lights: [.defaultSun, .defaultPoint],
            viewport: AetherViewportState(exposureStops: 1.5, gizmoMode: 2,
                                          gaussianDebugMode: 3, shadowDebugMode: 1,
                                          shadowDebugSlice: 2),
            playback: AetherPlaybackState(animationClip: 1, seconds: 2.5,
                                           playing: false, loop: false),
            selection: AetherSelectionState(meshEntity: 1, gaussian: nil,
                                             material: 1, light: 2),
            camera: AetherCameraState(positionX: 1, positionY: 2, positionZ: 3,
                                      yaw: 0.2, pitch: -0.1,
                                      verticalFieldOfViewRadians: 0.9)
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(state)
        let decoded = try JSONDecoder().decode(AetherProjectState.self, from: data)
        guard decoded == state else {
            throw TestFailure("AETHER project state did not round-trip")
        }
        let legacy = Data("""
            {"schemaVersion":1,"displayName":"Legacy","scenePath":"old.gltf",
             "selectedWorkspace":"Scene"}
            """.utf8)
        let migrated = try JSONDecoder().decode(AetherProjectState.self, from: legacy)
        guard migrated.schemaVersion == AetherProjectState.currentSchemaVersion &&
              migrated.entityTransformOverrides.isEmpty else {
            throw TestFailure("Schema-1 project did not migrate to empty transform overrides")
        }
        guard migrated.materialOverrides.isEmpty else {
            throw TestFailure("Schema-1 project unexpectedly produced material overrides")
        }
        guard migrated.lights == [.defaultSun] else {
            throw TestFailure("Schema-1 project did not receive the production default sun")
        }
        guard migrated.viewport == AetherViewportState() &&
              migrated.playback == AetherPlaybackState() &&
              migrated.selection == AetherSelectionState() &&
              migrated.camera == AetherCameraState() else {
            throw TestFailure("Schema-1 project did not receive generalized scene defaults")
        }
        let schema2 = Data("""
            {"schemaVersion":2,"displayName":"Prior","lights":[]}
            """.utf8)
        let migrated2 = try JSONDecoder().decode(AetherProjectState.self, from: schema2)
        guard migrated2.schemaVersion == 4 && migrated2.lights == [.defaultSun] &&
              migrated2.dynamicMeshPath == nil else {
            throw TestFailure("Schema-2 project did not migrate to schema 4")
        }
        let hostile = Data("""
            {"schemaVersion":3,"viewport":{"exposureStops":99,"gizmoMode":9,
             "gaussianDebugMode":9,"shadowDebugMode":9,"shadowDebugSlice":99},
             "playback":{"animationClip":-4,"seconds":-2,"playing":true,"loop":true},
             "selection":{"meshEntity":0,"gaussian":-1,"material":0,"light":99},
             "camera":{"positionX":0,"positionY":0,"positionZ":2.5,"yaw":0,"pitch":2,
             "verticalFieldOfViewRadians":4}}
            """.utf8)
        let normalized = try JSONDecoder().decode(AetherProjectState.self, from: hostile)
        guard normalized.viewport.exposureStops == 16 && normalized.viewport.gizmoMode == 2 &&
              normalized.viewport.gaussianDebugMode == 6 &&
              normalized.viewport.shadowDebugMode == 2 &&
              normalized.viewport.shadowDebugSlice == 11 &&
              normalized.playback.animationClip == nil && normalized.playback.seconds == 0 &&
              normalized.selection == AetherSelectionState() &&
              normalized.camera == AetherCameraState() else {
            throw TestFailure("Schema-3 hostile editor state was not normalized during migration")
        }
        guard AetherProjectDocument.readableContentTypes == [.aetherProject] else {
            throw TestFailure("AETHER project content type is not registered")
        }
        let coverageData = Data("""
            {"passed":false,"inputImages":10,"registeredImages":6,
             "registrationRatio":0.6,"trackedPoints":12,"meanTrackLength":2.5,
             "connectedImages":4,"connectedImageRatio":0.6666667,
             "baselineDiagonal":1.25,"maximumViewAngleDegrees":8.5,
             "issues":["Image overlap graph is fragmented"]}
            """.utf8)
        let coverage = try JSONDecoder().decode(SparseCoverageReport.self, from: coverageData)
        guard !coverage.passed && coverage.registeredImages == 6 &&
              coverage.issues == ["Image overlap graph is fragmented"] else {
            throw TestFailure("Sparse coverage evidence did not decode for Studio")
        }
        let checkpointRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("aether-checkpoint-discovery-test")
        try? FileManager.default.removeItem(at: checkpointRoot)
        let exports = checkpointRoot.appendingPathComponent("exports")
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        try Data("ply\nfixture".utf8).write(to: exports.appendingPathComponent("checkpoint_010.ply"))
        try Data("ply\nfixture".utf8).write(to: exports.appendingPathComponent("checkpoint_002.ply"))
        try Data().write(to: exports.appendingPathComponent("checkpoint_003.ply"))
        try Data("ignored".utf8).write(to: exports.appendingPathComponent("checkpoint_bad.ply"))
        let checkpoints = try TrainingCheckpoint.discover(in: checkpointRoot)
        guard checkpoints.map(\.iteration) == [2, 10] && checkpoints.allSatisfy({ $0.bytes > 0 }) else {
            throw TestFailure("Training checkpoints were not strictly discovered and ordered")
        }
        try FileManager.default.removeItem(at: checkpointRoot)
        print("AETHER Swift document tests passed")
    }
}

private struct TestFailure: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}
