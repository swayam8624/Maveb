import SwiftUI
import UniformTypeIdentifiers

extension UTType {
    static let aetherProject = UTType(exportedAs: "com.swayamsingal.aether.project")
}

struct AetherProjectState: Codable, Equatable {
    static let currentSchemaVersion = 5

    var schemaVersion = currentSchemaVersion
    var displayName = "Untitled AETHER Project"
    var scenePath: String?
    var dynamicMeshPath: String?
    var worldArchivePath: String?
    var selectedWorkspace = "Scene"
    var entityTransformOverrides: [String: AetherTransformOverride] = [:]
    var materialOverrides: [String: AetherMaterialOverride] = [:]
    var lights: [AetherLightState] = [.defaultSun]
    var viewport = AetherViewportState()
    var playback = AetherPlaybackState()
    var selection = AetherSelectionState()
    var camera = AetherCameraState()

    init(schemaVersion: Int = currentSchemaVersion,
         displayName: String = "Untitled AETHER Project",
         scenePath: String? = nil,
         dynamicMeshPath: String? = nil,
         worldArchivePath: String? = nil,
         selectedWorkspace: String = "Scene",
         entityTransformOverrides: [String: AetherTransformOverride] = [:],
         materialOverrides: [String: AetherMaterialOverride] = [:],
         lights: [AetherLightState] = [.defaultSun],
         viewport: AetherViewportState = AetherViewportState(),
         playback: AetherPlaybackState = AetherPlaybackState(),
         selection: AetherSelectionState = AetherSelectionState(),
         camera: AetherCameraState = AetherCameraState()) {
        self.schemaVersion = schemaVersion
        self.displayName = displayName
        self.scenePath = scenePath
        self.dynamicMeshPath = dynamicMeshPath
        self.worldArchivePath = worldArchivePath
        self.selectedWorkspace = selectedWorkspace
        self.entityTransformOverrides = entityTransformOverrides
        self.materialOverrides = materialOverrides
        self.lights = lights
        self.viewport = viewport
        self.playback = playback
        self.selection = selection
        self.camera = camera
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, displayName, scenePath, dynamicMeshPath, worldArchivePath,
             selectedWorkspace, entityTransformOverrides,
             materialOverrides, lights, viewport, playback, selection, camera
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let sourceVersion = try values.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        guard (1...Self.currentSchemaVersion).contains(sourceVersion) else {
            throw DecodingError.dataCorruptedError(forKey: .schemaVersion, in: values,
                                                    debugDescription: "Unsupported project schema")
        }
        schemaVersion = Self.currentSchemaVersion
        displayName = try values.decodeIfPresent(String.self, forKey: .displayName) ??
                      "Untitled AETHER Project"
        scenePath = try values.decodeIfPresent(String.self, forKey: .scenePath)
        dynamicMeshPath = try values.decodeIfPresent(String.self, forKey: .dynamicMeshPath)
        worldArchivePath = try values.decodeIfPresent(String.self, forKey: .worldArchivePath)
        selectedWorkspace = try values.decodeIfPresent(String.self, forKey: .selectedWorkspace) ??
                            "Scene"
        entityTransformOverrides =
            try values.decodeIfPresent([String: AetherTransformOverride].self,
                                       forKey: .entityTransformOverrides) ?? [:]
        materialOverrides = try values.decodeIfPresent(AetherMaterialOverrideMap.self,
                                                        forKey: .materialOverrides) ?? [:]
        lights = try values.decodeIfPresent([AetherLightState].self, forKey: .lights) ?? [.defaultSun]
        if lights.isEmpty { lights = [.defaultSun] }
        viewport = try values.decodeIfPresent(AetherViewportState.self, forKey: .viewport) ?? .init()
        playback = try values.decodeIfPresent(AetherPlaybackState.self, forKey: .playback) ?? .init()
        selection = try values.decodeIfPresent(AetherSelectionState.self, forKey: .selection) ?? .init()
        camera = try values.decodeIfPresent(AetherCameraState.self, forKey: .camera) ?? .init()
        viewport.exposureStops = viewport.exposureStops.isFinite
            ? min(16, max(-16, viewport.exposureStops)) : 0
        viewport.gizmoMode = min(2, max(0, viewport.gizmoMode))
        viewport.gaussianDebugMode = min(6, max(0, viewport.gaussianDebugMode))
        viewport.shadowDebugMode = min(2, max(0, viewport.shadowDebugMode))
        viewport.shadowDebugSlice = min(viewport.shadowDebugMode == 1 ? 3 : 11,
                                        max(0, viewport.shadowDebugSlice))
        if !playback.seconds.isFinite || playback.seconds < 0 { playback.seconds = 0 }
        if let clip = playback.animationClip, clip < 0 { playback.animationClip = nil }
        if let entity = selection.meshEntity, entity <= 0 { selection.meshEntity = nil }
        if let gaussian = selection.gaussian, gaussian <= 0 { selection.gaussian = nil }
        if let material = selection.material, material <= 0 { selection.material = nil }
        selection.light = min(lights.count, max(1, selection.light))
        let cameraValues = [camera.positionX, camera.positionY, camera.positionZ, camera.yaw,
                            camera.pitch, camera.verticalFieldOfViewRadians]
        if cameraValues.contains(where: { !$0.isFinite }) ||
            camera.pitch < -1.553343 || camera.pitch > 1.553343 ||
            camera.verticalFieldOfViewRadians < 0.1745329 ||
            camera.verticalFieldOfViewRadians > 2.9670597 {
            camera = AetherCameraState()
        }
    }
}

private typealias AetherMaterialOverrideMap = [String: AetherMaterialOverride]

struct AetherViewportState: Codable, Equatable {
    var exposureStops: Float = 0
    var gizmoMode = 0
    var gaussianDebugMode = 0
    var shadowDebugMode = 0
    var shadowDebugSlice = 0
}

struct AetherPlaybackState: Codable, Equatable {
    var animationClip: Int?
    var seconds: Float = 0
    var playing = true
    var loop = true
    var values: [NSNumber] {
        [NSNumber(value: animationClip ?? -1), NSNumber(value: seconds), NSNumber(value: playing),
         NSNumber(value: loop)]
    }
}

struct AetherSelectionState: Codable, Equatable {
    var meshEntity: Int?
    var gaussian: Int?
    var material: Int?
    var light = 1
}

struct AetherCameraState: Codable, Equatable {
    var positionX: Float = 0
    var positionY: Float = 0
    var positionZ: Float = 2.5
    var yaw: Float = 0
    var pitch: Float = 0
    var verticalFieldOfViewRadians: Float = 1.0471976
    var values: [Float] {
        [positionX, positionY, positionZ, yaw, pitch, verticalFieldOfViewRadians]
    }
}

struct AetherLightState: Codable, Equatable {
    static let defaultSun = AetherLightState(type: 0, positionX: 0, positionY: 0, positionZ: 0,
                                             range: 10, directionX: -0.4, directionY: -1,
                                             directionZ: -0.6, colorRed: 1, colorGreen: 0.95,
                                             colorBlue: 0.85, intensity: 4,
                                             innerConeRadians: 0.35, outerConeRadians: 0.55)
    static let defaultPoint = AetherLightState(type: 1, positionX: 0, positionY: 2, positionZ: 0,
                                               range: 10, directionX: 0, directionY: -1,
                                               directionZ: 0, colorRed: 1, colorGreen: 1,
                                               colorBlue: 1, intensity: 10,
                                               innerConeRadians: 0.35, outerConeRadians: 0.55)

    var type: Int
    var positionX, positionY, positionZ: Float
    var range: Float
    var directionX, directionY, directionZ: Float
    var colorRed, colorGreen, colorBlue: Float
    var intensity: Float
    var innerConeRadians, outerConeRadians: Float

    var values: [Float] {
        [Float(type), positionX, positionY, positionZ, range, directionX, directionY, directionZ,
         colorRed, colorGreen, colorBlue, intensity, innerConeRadians, outerConeRadians]
    }
}

struct AetherMaterialOverride: Codable, Equatable {
    var baseRed: Float = 1
    var baseGreen: Float = 1
    var baseBlue: Float = 1
    var baseAlpha: Float = 1
    var emissiveRed: Float = 0
    var emissiveGreen: Float = 0
    var emissiveBlue: Float = 0
    var metallic: Float = 1
    var roughness: Float = 1
    var normalScale: Float = 1
    var occlusionStrength: Float = 1
    var alphaCutoff: Float = 0.5

    init(values: [Float] = [1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 0.5]) {
        guard values.count == 12 else { return }
        baseRed = values[0]; baseGreen = values[1]; baseBlue = values[2]; baseAlpha = values[3]
        emissiveRed = values[4]; emissiveGreen = values[5]; emissiveBlue = values[6]
        metallic = values[7]; roughness = values[8]; normalScale = values[9]
        occlusionStrength = values[10]; alphaCutoff = values[11]
    }

    var values: [Float] {
        [baseRed, baseGreen, baseBlue, baseAlpha, emissiveRed, emissiveGreen, emissiveBlue,
         metallic, roughness, normalScale, occlusionStrength, alphaCutoff]
    }
}

struct AetherTransformOverride: Codable, Equatable {
    var translationX: Float = 0
    var translationY: Float = 0
    var translationZ: Float = 0
    var rotationX: Float = 0
    var rotationY: Float = 0
    var rotationZ: Float = 0
    var rotationW: Float = 1
    var scaleX: Float = 1
    var scaleY: Float = 1
    var scaleZ: Float = 1

    init(values: [Float] = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]) {
        guard values.count == 10 else { return }
        translationX = values[0]; translationY = values[1]; translationZ = values[2]
        rotationX = values[3]; rotationY = values[4]; rotationZ = values[5]; rotationW = values[6]
        scaleX = values[7]; scaleY = values[8]; scaleZ = values[9]
    }

    var values: [Float] {
        [translationX, translationY, translationZ, rotationX, rotationY, rotationZ, rotationW,
         scaleX, scaleY, scaleZ]
    }
}

struct AetherProjectDocument: FileDocument {
    static let readableContentTypes: [UTType] = [.aetherProject]
    static let writableContentTypes: [UTType] = [.aetherProject]

    var state = AetherProjectState()

    init() {}

    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else {
            throw CocoaError(.fileReadCorruptFile)
        }
        let decoded = try JSONDecoder().decode(AetherProjectState.self, from: data)
        state = decoded
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return FileWrapper(regularFileWithContents: try encoder.encode(state))
    }
}
