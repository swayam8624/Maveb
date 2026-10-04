import AppKit
import SwiftUI

struct AetherViewport: NSViewRepresentable {
    let scenePath: String?
    let dynamicMeshPath: String?
    @Binding var selectedGaussianId: Int?
    @Binding var selectedMeshId: Int?
    @Binding var selectedMeshTransform: AetherTransformOverride?
    @Binding var meshEntityNames: [String]
    @Binding var selectedMaterialId: Int?
    @Binding var selectedMaterial: AetherMaterialOverride?
    @Binding var materialNames: [String]
    @Binding var transformOverrides: [String: AetherTransformOverride]
    @Binding var camera: AetherCameraState
    let playback: AetherPlaybackState
    let materialOverrides: [String: AetherMaterialOverride]
    let lights: [AetherLightState]
    let gaussianDebugMode: Int
    let shadowDebugMode: Int
    let shadowDebugSlice: Int
    let gizmoMode: Int
    let exposureStops: Float
    @AppStorage("preferredFramesPerSecond") private var preferredFramesPerSecond = 60

    final class Coordinator {
        var scenePath: String?
        var dynamicMeshPath: String?
        var selectedMeshId: Int?
        var appliedOverrides: [String: AetherTransformOverride] = [:]
        var selectedMaterialId: Int?
        var appliedMaterials: [String: AetherMaterialOverride] = [:]
        var appliedLights: [AetherLightState] = []
        var appliedCamera = AetherCameraState()
        var appliedPlayback = AetherPlaybackState()
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> AetherViewportView {
        let view = AetherViewportView(frame: .zero)
        view.preferredFramesPerSecond = preferredFramesPerSecond
        view.onEntityPicked = { entityId, gaussian in
            selectedGaussianId = gaussian && entityId != 0 ? Int(entityId) : nil
            selectedMeshId = !gaussian && entityId != 0 ? Int(entityId) : nil
            selectedMeshTransform = !gaussian ? readTransform(view, entityId: Int(entityId)) : nil
        }
        view.onMeshEntitiesChanged = { names in meshEntityNames = names }
        view.onMeshTransformEdited = { entityId, numbers in
            let transform = AetherTransformOverride(values: numbers.map(\.floatValue))
            selectedMeshId = Int(entityId)
            selectedMeshTransform = transform
            transformOverrides[String(entityId)] = transform
        }
        view.onMaterialsChanged = { names in materialNames = names }
        view.onCameraChanged = { values in
            guard values.count == 6 else { return }
            camera = AetherCameraState(positionX: values[0].floatValue,
                                       positionY: values[1].floatValue,
                                       positionZ: values[2].floatValue,
                                       yaw: values[3].floatValue, pitch: values[4].floatValue,
                                       verticalFieldOfViewRadians: values[5].floatValue)
        }
        view.scenePath = scenePath
        view.dynamicMeshPath = dynamicMeshPath
        applyOverrides(transformOverrides, to: view, previous: [:])
        applyMaterialOverrides(materialOverrides, to: view, previous: [:])
        applyLights(lights, to: view)
        context.coordinator.scenePath = scenePath
        context.coordinator.dynamicMeshPath = dynamicMeshPath
        context.coordinator.appliedOverrides = transformOverrides
        context.coordinator.appliedMaterials = materialOverrides
        context.coordinator.appliedLights = lights
        context.coordinator.appliedCamera = camera
        context.coordinator.appliedPlayback = playback
        view.gaussianDebugMode = gaussianDebugMode
        view.shadowDebugMode = shadowDebugMode
        view.shadowDebugSlice = shadowDebugSlice
        view.gizmoMode = gizmoMode
        view.cameraState = camera.values.map { NSNumber(value: $0) }
        view.playbackState = playback.values
        view.exposureStops = exposureStops
        return view
    }

    func updateNSView(_ nsView: AetherViewportView, context: Context) {
        nsView.preferredFramesPerSecond = preferredFramesPerSecond
        nsView.onEntityPicked = { entityId, gaussian in
            selectedGaussianId = gaussian && entityId != 0 ? Int(entityId) : nil
            selectedMeshId = !gaussian && entityId != 0 ? Int(entityId) : nil
            selectedMeshTransform = !gaussian ? readTransform(nsView, entityId: Int(entityId)) : nil
        }
        nsView.onMeshEntitiesChanged = { names in meshEntityNames = names }
        nsView.onMeshTransformEdited = { entityId, numbers in
            let transform = AetherTransformOverride(values: numbers.map(\.floatValue))
            selectedMeshId = Int(entityId)
            selectedMeshTransform = transform
            transformOverrides[String(entityId)] = transform
        }
        nsView.selectedMeshEntity = selectedMeshId ?? 0
        nsView.onMaterialsChanged = { names in materialNames = names }
        nsView.onCameraChanged = { values in
            guard values.count == 6 else { return }
            camera = AetherCameraState(positionX: values[0].floatValue,
                                       positionY: values[1].floatValue,
                                       positionZ: values[2].floatValue,
                                       yaw: values[3].floatValue, pitch: values[4].floatValue,
                                       verticalFieldOfViewRadians: values[5].floatValue)
        }
        if context.coordinator.scenePath != scenePath {
            nsView.scenePath = scenePath
            context.coordinator.scenePath = scenePath
            context.coordinator.appliedOverrides = [:]
            nsView.cameraState = camera.values.map { NSNumber(value: $0) }
            context.coordinator.appliedCamera = camera
            nsView.playbackState = playback.values
            context.coordinator.appliedPlayback = playback
        }
        if context.coordinator.dynamicMeshPath != dynamicMeshPath {
            nsView.dynamicMeshPath = dynamicMeshPath
            context.coordinator.dynamicMeshPath = dynamicMeshPath
        }
        if context.coordinator.appliedOverrides != transformOverrides {
            applyOverrides(transformOverrides, to: nsView,
                           previous: context.coordinator.appliedOverrides)
            context.coordinator.appliedOverrides = transformOverrides
            if let selectedMeshId {
                let snapshot = readTransform(nsView, entityId: selectedMeshId)
                DispatchQueue.main.async { selectedMeshTransform = snapshot }
            }
        }
        if context.coordinator.appliedMaterials != materialOverrides {
            applyMaterialOverrides(materialOverrides, to: nsView,
                                   previous: context.coordinator.appliedMaterials)
            context.coordinator.appliedMaterials = materialOverrides
            if let selectedMaterialId {
                let snapshot = readMaterial(nsView, materialId: selectedMaterialId)
                DispatchQueue.main.async { selectedMaterial = snapshot }
            }
        }
        if context.coordinator.appliedLights != lights {
            applyLights(lights, to: nsView)
            context.coordinator.appliedLights = lights
        }
        if context.coordinator.appliedCamera != camera {
            nsView.cameraState = camera.values.map { NSNumber(value: $0) }
            context.coordinator.appliedCamera = camera
        }
        if context.coordinator.appliedPlayback != playback {
            nsView.playbackState = playback.values
            context.coordinator.appliedPlayback = playback
        }
        if context.coordinator.selectedMeshId != selectedMeshId {
            context.coordinator.selectedMeshId = selectedMeshId
            let snapshot = selectedMeshId.flatMap { readTransform(nsView, entityId: $0) }
            DispatchQueue.main.async { selectedMeshTransform = snapshot }
        }
        if context.coordinator.selectedMaterialId != selectedMaterialId {
            context.coordinator.selectedMaterialId = selectedMaterialId
            let snapshot = selectedMaterialId.flatMap { readMaterial(nsView, materialId: $0) }
            DispatchQueue.main.async { selectedMaterial = snapshot }
        }
        nsView.gaussianDebugMode = gaussianDebugMode
        nsView.shadowDebugMode = shadowDebugMode
        nsView.shadowDebugSlice = shadowDebugSlice
        nsView.gizmoMode = gizmoMode
        nsView.exposureStops = exposureStops
        _ = nsView.rendererStatus
    }

    private func readTransform(_ view: AetherViewportView,
                               entityId: Int) -> AetherTransformOverride? {
        guard entityId > 0,
              let numbers = view.meshTransform(forEntity: entityId), numbers.count == 11 else {
            return nil
        }
        return AetherTransformOverride(values: numbers.prefix(10).map(\.floatValue))
    }

    private func applyOverrides(_ overrides: [String: AetherTransformOverride],
                                to view: AetherViewportView,
                                previous: [String: AetherTransformOverride]) {
        for key in previous.keys where overrides[key] == nil {
            if let entityId = Int(key) { _ = view.clearMeshTransform(forEntity: entityId) }
        }
        for (key, transform) in overrides where previous[key] != transform {
            guard let entityId = Int(key) else { continue }
            let numbers = transform.values.map { NSNumber(value: $0) }
            _ = view.setMeshTransformForEntity(entityId, values: numbers)
        }
    }

    private func readMaterial(_ view: AetherViewportView,
                              materialId: Int) -> AetherMaterialOverride? {
        guard materialId > 0, let numbers = view.material(forId: materialId), numbers.count == 13
        else { return nil }
        return AetherMaterialOverride(values: numbers.prefix(12).map(\.floatValue))
    }

    private func applyMaterialOverrides(_ overrides: [String: AetherMaterialOverride],
                                        to view: AetherViewportView,
                                        previous: [String: AetherMaterialOverride]) {
        for key in previous.keys where overrides[key] == nil {
            if let materialId = Int(key) { _ = view.clearMaterial(forId: materialId) }
        }
        for (key, material) in overrides where previous[key] != material {
            guard let materialId = Int(key) else { continue }
            _ = view.setMaterialForId(materialId,
                                      values: material.values.map { NSNumber(value: $0) })
        }
    }

    private func applyLights(_ lights: [AetherLightState], to view: AetherViewportView) {
        let payload = lights.map { light in light.values.map { NSNumber(value: $0) } }
        _ = view.replaceLights(payload)
    }
}
