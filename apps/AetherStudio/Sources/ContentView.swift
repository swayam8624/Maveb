import AppKit
import SwiftUI
import UniformTypeIdentifiers

private enum Workspace: String, CaseIterable, Identifiable {
    case scene = "Scene"
    case importScene = "Import"
    case reconstruction = "Reconstruction"
    case materials = "Materials"
    case lighting = "Lighting"
    case research = "Research"
    case benchmark = "Benchmark"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .scene: "cube.transparent"
        case .importScene: "square.and.arrow.down"
        case .reconstruction: "camera.metering.matrix"
        case .materials: "circle.hexagongrid"
        case .lighting: "sun.max"
        case .research: "waveform.path.ecg.rectangle"
        case .benchmark: "gauge.with.dots.needle.67percent"
        }
    }

    var subtitle: String {
        switch self {
        case .scene: "Inspect, select, and transform rendered content."
        case .importScene: "Bring Gaussian, AETHER, or glTF assets into the project."
        case .reconstruction: "Validate and rebuild local captures without uploading data."
        case .materials: "Tune physically based material factors on the active mesh."
        case .lighting: "Shape the scene with lights, shadows, and exposure."
        case .research: "Inspect renderer research views and correctness attachments."
        case .benchmark: "Review the scene with benchmark-oriented debug modes."
        }
    }
}

private enum GaussianDebugMode: Int, CaseIterable, Identifiable {
    case appearance, depth, sourceIds, tileOccupancy, opacity, shBands, sortRank
    var id: Int { rawValue }
    var label: String {
        switch self {
        case .appearance: "Appearance"
        case .depth: "Depth"
        case .sourceIds: "Source IDs"
        case .tileOccupancy: "Tile Occupancy"
        case .opacity: "Opacity"
        case .shBands: "SH Bands"
        case .sortRank: "Sort Rank"
        }
    }
}

private enum ShadowDebugMode: Int, CaseIterable, Identifiable {
    case disabled, directional, local
    var id: Int { rawValue }
    var label: String {
        switch self {
        case .disabled: "Final Image"
        case .directional: "Directional Shadow"
        case .local: "Local Shadow"
        }
    }
}

private enum GizmoMode: Int, CaseIterable, Identifiable {
    case translate, rotate, scale
    var id: Int { rawValue }
    var label: String {
        switch self {
        case .translate: "Move"
        case .rotate: "Rotate"
        case .scale: "Scale"
        }
    }
    var symbol: String {
        switch self {
        case .translate: "arrow.up.and.down.and.arrow.left.and.right"
        case .rotate: "rotate.3d"
        case .scale: "arrow.up.left.and.arrow.down.right"
        }
    }
}

private struct StudioPanel<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        content
            .padding(14)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.primary.opacity(0.08), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.13), radius: 18, y: 8)
    }
}

private struct PanelTitle: View {
    let title: String
    let symbol: String
    var body: some View {
        Label(title.uppercased(), systemImage: symbol)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .tracking(0.8)
    }
}

private struct StatusPill: View {
    let text: String
    let symbol: String
    let color: Color
    var body: some View {
        Label(text, systemImage: symbol)
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(color.opacity(0.10), in: Capsule())
            .overlay { Capsule().stroke(color.opacity(0.18), lineWidth: 1) }
    }
}

private struct MeshOutliner: View {
    let names: [String]
    @Binding var selectedId: Int?

    var body: some View {
        StudioPanel {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    PanelTitle(title: "Outliner", symbol: "list.bullet.indent")
                    Spacer()
                    Text("\(names.count)")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                }
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(names.indices, id: \.self) { index in
                            let entityId = index + 1
                            Button {
                                selectedId = entityId
                            } label: {
                                HStack(spacing: 8) {
                                    Image(systemName: "cube")
                                        .font(.caption)
                                        .frame(width: 16)
                                    Text(names[index]).lineLimit(1)
                                    Spacer(minLength: 8)
                                    Text("#\(entityId)")
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(.tertiary)
                                }
                                .contentShape(Rectangle())
                                .padding(.horizontal, 8)
                                .padding(.vertical, 7)
                                .background {
                                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                                        .fill(selectedId == entityId
                                              ? Color.accentColor.opacity(0.16)
                                              : Color.clear)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxHeight: 250)
            }
            .frame(width: 238)
        }
    }
}

private struct MeshTransformInspector: View {
    @Binding var transform: AetherTransformOverride

    var body: some View {
        StudioPanel {
            VStack(alignment: .leading, spacing: 12) {
                PanelTitle(title: "Transform", symbol: "move.3d")
                vectorRow("Position", [binding(\.translationX), binding(\.translationY), binding(\.translationZ)])
                vectorRow("Quaternion", [binding(\.rotationX), binding(\.rotationY), binding(\.rotationZ), binding(\.rotationW)])
                vectorRow("Scale", [binding(\.scaleX), binding(\.scaleY), binding(\.scaleZ)])
            }
            .frame(width: 294)
        }
    }

    private func binding(_ keyPath: WritableKeyPath<AetherTransformOverride, Float>) -> Binding<Float> {
        Binding(get: { transform[keyPath: keyPath] }, set: { transform[keyPath: keyPath] = $0 })
    }

    private func vectorRow(_ label: String, _ values: [Binding<Float>]) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 5) {
                ForEach(values.indices, id: \.self) { index in
                    TextField("", value: values[index], format: .number.precision(.fractionLength(3)))
                        .textFieldStyle(.roundedBorder)
                        .font(.caption.monospacedDigit())
                }
            }
        }
    }
}

private struct MaterialInspector: View {
    let names: [String]
    @Binding var selectedId: Int?
    @Binding var material: AetherMaterialOverride

    var body: some View {
        StudioPanel {
            VStack(alignment: .leading, spacing: 12) {
                PanelTitle(title: "Material", symbol: "circle.hexagongrid")
                Picker("Material", selection: $selectedId) {
                    Text("Select material").tag(Int?.none)
                    ForEach(names.indices, id: \.self) { index in
                        Text(names[index]).tag(Int?.some(index + 1))
                    }
                }
                .labelsHidden()
                factorRow("Base RGBA", [binding(\.baseRed), binding(\.baseGreen), binding(\.baseBlue), binding(\.baseAlpha)])
                factorRow("Emissive", [binding(\.emissiveRed), binding(\.emissiveGreen), binding(\.emissiveBlue)])
                slider("Metallic", binding(\.metallic), 0...1)
                slider("Roughness", binding(\.roughness), 0...1)
                slider("Normal", binding(\.normalScale), 0...8)
                slider("Occlusion", binding(\.occlusionStrength), 0...1)
                slider("Alpha Cutoff", binding(\.alphaCutoff), 0...1)
            }
            .frame(width: 316)
        }
    }

    private func binding(_ keyPath: WritableKeyPath<AetherMaterialOverride, Float>) -> Binding<Float> {
        Binding(get: { material[keyPath: keyPath] }, set: { material[keyPath: keyPath] = $0 })
    }

    private func factorRow(_ label: String, _ values: [Binding<Float>]) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 5) {
                ForEach(values.indices, id: \.self) { index in
                    TextField("", value: values[index], format: .number.precision(.fractionLength(3)))
                        .textFieldStyle(.roundedBorder)
                        .font(.caption.monospacedDigit())
                }
            }
        }
    }

    private func slider(_ label: String, _ value: Binding<Float>, _ range: ClosedRange<Float>) -> some View {
        HStack(spacing: 8) {
            Text(label).font(.caption).foregroundStyle(.secondary).frame(width: 76, alignment: .leading)
            Slider(value: value, in: range)
            Text(value.wrappedValue.formatted(.number.precision(.fractionLength(2))))
                .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                .frame(width: 38, alignment: .trailing)
        }
    }
}

private struct LightInspector: View {
    @Binding var selectedId: Int
    let count: Int
    @Binding var light: AetherLightState
    let add: () -> Void
    let remove: () -> Void

    var body: some View {
        StudioPanel {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    PanelTitle(title: "Lighting", symbol: "lightbulb.led")
                    Spacer()
                    Button(action: add) { Image(systemName: "plus") }
                        .buttonStyle(.borderless).help("Add light")
                    Button(action: remove) { Image(systemName: "minus") }
                        .buttonStyle(.borderless).disabled(count <= 1).help("Remove selected light")
                }
                Picker("Light", selection: $selectedId) {
                    ForEach(1...max(count, 1), id: \.self) { id in Text("Light #\(id)").tag(id) }
                }
                .labelsHidden()
                Picker("Type", selection: $light.type) {
                    Text("Directional").tag(0)
                    Text("Point").tag(1)
                    Text("Spot").tag(2)
                }
                .pickerStyle(.segmented)
                vectorRow("Position", [binding(\.positionX), binding(\.positionY), binding(\.positionZ)])
                vectorRow("Direction", [binding(\.directionX), binding(\.directionY), binding(\.directionZ)])
                vectorRow("Color", [binding(\.colorRed), binding(\.colorGreen), binding(\.colorBlue)])
                slider("Intensity", binding(\.intensity), 0...100)
                if light.type != 0 { slider("Range", binding(\.range), 0.05...100) }
                if light.type == 2 {
                    slider("Inner Cone", binding(\.innerConeRadians), 0.01...1.5)
                    slider("Outer Cone", binding(\.outerConeRadians), 0.02...1.56)
                }
            }
            .frame(width: 316)
        }
    }

    private func binding(_ keyPath: WritableKeyPath<AetherLightState, Float>) -> Binding<Float> {
        Binding(get: { light[keyPath: keyPath] }, set: { light[keyPath: keyPath] = $0 })
    }

    private func vectorRow(_ label: String, _ values: [Binding<Float>]) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 5) {
                ForEach(values.indices, id: \.self) { index in
                    TextField("", value: values[index], format: .number.precision(.fractionLength(3)))
                        .textFieldStyle(.roundedBorder)
                        .font(.caption.monospacedDigit())
                }
            }
        }
    }

    private func slider(_ label: String, _ value: Binding<Float>, _ range: ClosedRange<Float>) -> some View {
        HStack(spacing: 8) {
            Text(label).font(.caption).foregroundStyle(.secondary).frame(width: 76, alignment: .leading)
            Slider(value: value, in: range)
            Text(value.wrappedValue.formatted(.number.precision(.fractionLength(2))))
                .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                .frame(width: 42, alignment: .trailing)
        }
    }
}

struct ContentView: View {
    @Binding var document: AetherProjectDocument
    let projectURL: URL?

    @State private var selection: Workspace? = .scene
    @State private var selectedGaussianId: Int?
    @State private var selectedMeshId: Int?
    @State private var meshEntityNames: [String] = []
    @State private var selectedMeshTransform: AetherTransformOverride?
    @State private var materialNames: [String] = []
    @State private var selectedMaterialId: Int?
    @State private var selectedMaterial: AetherMaterialOverride?
    @State private var selectedLightId = 1
    @State private var gaussianDebugMode: GaussianDebugMode = .appearance
    @State private var shadowDebugMode: ShadowDebugMode = .disabled
    @State private var shadowDebugSlice = 0
    @State private var gizmoMode: GizmoMode = .translate
    @State private var exposureStops: Float = 0

    @Environment(\.undoManager) private var undoManager
    @AppStorage("showRendererDiagnostics") private var showRendererDiagnostics = false

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            VStack(spacing: 0) {
                workspaceHeader
                Divider().opacity(0.55)
                workspaceContent
            }
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .navigationSplitViewStyle(.balanced)
        .onChange(of: selection) { _, newValue in
            guard let newValue else { return }
            document.state.selectedWorkspace = newValue.rawValue
        }
        .onChange(of: selectedMeshId) { _, value in document.state.selection.meshEntity = value }
        .onChange(of: selectedGaussianId) { _, value in document.state.selection.gaussian = value }
        .onChange(of: selectedMaterialId) { _, value in document.state.selection.material = value }
        .onChange(of: selectedLightId) { _, value in document.state.selection.light = value }
        .onChange(of: exposureStops) { _, value in document.state.viewport.exposureStops = value }
        .onChange(of: gizmoMode) { _, value in document.state.viewport.gizmoMode = value.rawValue }
        .onChange(of: gaussianDebugMode) { _, value in document.state.viewport.gaussianDebugMode = value.rawValue }
        .onChange(of: shadowDebugMode) { _, value in document.state.viewport.shadowDebugMode = value.rawValue }
        .onChange(of: shadowDebugSlice) { _, value in document.state.viewport.shadowDebugSlice = value }
        .onChange(of: document.state.scenePath) { _, _ in resetRendererSelection() }
        .onAppear { restoreProjectUIState() }
        .toolbar { studioToolbar }
    }

    private var sidebar: some View {
        VStack(spacing: 0) {
            HStack(spacing: 11) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.accentColor.opacity(0.14))
                    Image(systemName: "hexagon.fill")
                        .foregroundStyle(Color.accentColor)
                        .font(.system(size: 18, weight: .semibold))
                }
                .frame(width: 38, height: 38)
                VStack(alignment: .leading, spacing: 1) {
                    Text("AETHER").font(.headline.weight(.semibold))
                    Text("METAL STUDIO")
                        .font(.caption2.weight(.medium)).foregroundStyle(.secondary).tracking(1.1)
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 14)

            Divider().opacity(0.55)

            List(selection: $selection) {
                workspaceSection("WORKSPACE", [.scene, .importScene, .reconstruction])
                workspaceSection("LOOKDEV", [.materials, .lighting])
                workspaceSection("ANALYSIS", [.research, .benchmark])
            }
            .listStyle(.sidebar)

            Divider().opacity(0.55)

            HStack(spacing: 7) {
                Circle().fill(Color.green).frame(width: 7, height: 7)
                Text("Metal 3 • Local").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text("v0.1").font(.caption2.monospaced()).foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
        }
        .navigationSplitViewColumnWidth(min: 210, ideal: 238, max: 278)
    }

    @ViewBuilder
    private func workspaceSection(_ title: String, _ items: [Workspace]) -> some View {
        Section {
            ForEach(items) { workspace in
                Label(workspace.rawValue, systemImage: workspace.symbol).tag(workspace)
            }
        } header: {
            Text(title).font(.caption2.weight(.semibold)).foregroundStyle(.tertiary).tracking(0.8)
        }
    }

    private var workspaceHeader: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(Color.accentColor.opacity(0.10))
                Image(systemName: (selection ?? .scene).symbol)
                    .foregroundStyle(Color.accentColor)
                    .font(.system(size: 14, weight: .semibold))
            }
            .frame(width: 34, height: 34)

            VStack(alignment: .leading, spacing: 1) {
                Text(selection?.rawValue ?? "Scene").font(.headline)
                Text((selection ?? .scene).subtitle)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 20)
            if let scenePath = document.state.scenePath {
                StatusPill(text: URL(fileURLWithPath: scenePath).lastPathComponent,
                           symbol: "checkmark.circle.fill", color: .green)
                    .lineLimit(1)
            } else {
                StatusPill(text: "No scene loaded", symbol: "circle.dashed", color: .gray)
            }
        }
        .padding(.horizontal, 16)
        .frame(height: 58)
        .background(.bar)
    }

    @ViewBuilder
    private var workspaceContent: some View {
        switch selection ?? .scene {
        case .importScene:
            importWorkspace
        case .reconstruction:
            ReconstructionWorkspace()
        default:
            VStack(spacing: 0) {
                if selection == .lighting { exposureBar }
                viewport
            }
        }
    }

    private var exposureBar: some View {
        HStack(spacing: 12) {
            Label("Exposure", systemImage: "sun.max")
                .font(.caption.weight(.medium)).foregroundStyle(.secondary)
            Slider(value: $exposureStops, in: -8...8, step: 0.1).frame(maxWidth: 300)
            Text(String(format: "%+.1f EV", exposureStops))
                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                .frame(width: 62, alignment: .trailing)
            Spacer()
        }
        .padding(.horizontal, 16)
        .frame(height: 42)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider().opacity(0.45) }
    }

    private var viewport: some View {
        ZStack {
            AetherViewport(scenePath: resolvedScenePath,
                           dynamicMeshPath: resolvedDynamicMeshPath,
                           selectedGaussianId: $selectedGaussianId,
                           selectedMeshId: $selectedMeshId,
                           selectedMeshTransform: $selectedMeshTransform,
                           meshEntityNames: $meshEntityNames,
                           selectedMaterialId: $selectedMaterialId,
                           selectedMaterial: $selectedMaterial,
                           materialNames: $materialNames,
                           transformOverrides: $document.state.entityTransformOverrides,
                           camera: $document.state.camera,
                           playback: document.state.playback,
                           materialOverrides: document.state.materialOverrides,
                           lights: document.state.lights,
                           gaussianDebugMode: gaussianDebugMode.rawValue,
                           shadowDebugMode: shadowDebugMode.rawValue,
                           shadowDebugSlice: shadowDebugSlice,
                           gizmoMode: gizmoMode.rawValue,
                           exposureStops: exposureStops)
                .background(Color.black)

            if resolvedScenePath == nil { emptyViewportState }
        }
        .overlay(alignment: .topLeading) {
            if showRendererDiagnostics { rendererDiagnostics.padding(14) }
        }
        .overlay(alignment: .topTrailing) { inspectorOverlay.padding(14) }
        .overlay(alignment: .bottom) {
            if selectedMeshId != nil { gizmoDock.padding(.bottom, 18) }
        }
        .overlay(alignment: .bottomLeading) { viewportBadge.padding(14) }
        .onChange(of: selectedMeshId) { _, _ in selectedGaussianId = nil }
    }

    private var emptyViewportState: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle().fill(Color.accentColor.opacity(0.12)).frame(width: 68, height: 68)
                Image(systemName: "cube.transparent")
                    .font(.system(size: 30, weight: .light)).foregroundStyle(Color.accentColor)
            }
            VStack(spacing: 5) {
                Text("Start with a scene").font(.title3.weight(.semibold))
                Text("Import an AETHER capture, Gaussian PLY, or glTF asset to activate the Metal viewport.")
                    .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    .frame(maxWidth: 420)
            }
            Button { importScene() } label: {
                Label("Import Scene…", systemImage: "square.and.arrow.down")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .padding(30)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.primary.opacity(0.08)) }
    }

    private var rendererDiagnostics: some View {
        StudioPanel {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 7) {
                    Circle().fill(Color.green).frame(width: 7, height: 7)
                    Text(viewportModeLabel).font(.caption.weight(.semibold))
                }
                Text("Metal viewport active").font(.caption2).foregroundStyle(.secondary)
                if let selectedGaussianId {
                    Text("Gaussian #\(selectedGaussianId)").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
                if let selectedMeshId {
                    Text("Mesh entity #\(selectedMeshId)").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private var inspectorOverlay: some View {
        if selection == .lighting {
            LightInspector(selectedId: $selectedLightId,
                           count: document.state.lights.count,
                           light: selectedLightBinding,
                           add: addLight,
                           remove: removeSelectedLight)
        } else if selection == .materials && !materialNames.isEmpty {
            VStack(alignment: .trailing, spacing: 10) {
                MaterialInspector(names: materialNames,
                                  selectedId: $selectedMaterialId,
                                  material: selectedMaterialBinding)
                if selectedMaterialId != nil {
                    Button {
                        guard let selectedMaterialId else { return }
                        document.state.materialOverrides.removeValue(forKey: String(selectedMaterialId))
                        undoManager?.setActionName("Reset Material")
                    } label: {
                        Label("Reset Material", systemImage: "arrow.counterclockwise")
                    }
                    .buttonStyle(.bordered)
                }
            }
        } else if !meshEntityNames.isEmpty {
            VStack(alignment: .trailing, spacing: 10) {
                MeshOutliner(names: meshEntityNames, selectedId: $selectedMeshId)
                if selectedMeshId != nil && selectedMeshTransform != nil {
                    MeshTransformInspector(transform: selectedTransformBinding)
                    Button {
                        guard let selectedMeshId else { return }
                        document.state.entityTransformOverrides.removeValue(forKey: String(selectedMeshId))
                        undoManager?.setActionName("Reset Entity Transform")
                    } label: {
                        Label("Reset Transform", systemImage: "arrow.counterclockwise")
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
    }

    private var gizmoDock: some View {
        StudioPanel {
            HStack(spacing: 6) {
                ForEach(GizmoMode.allCases) { mode in
                    Button {
                        gizmoMode = mode
                    } label: {
                        Image(systemName: mode.symbol).frame(width: 28, height: 24)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(gizmoMode == mode ? Color.accentColor : Color.secondary)
                    .background {
                        RoundedRectangle(cornerRadius: 7, style: .continuous)
                            .fill(gizmoMode == mode ? Color.accentColor.opacity(0.14) : Color.clear)
                    }
                    .help(mode.label)
                }
            }
        }
    }

    private var viewportBadge: some View {
        Label(viewportModeLabel, systemImage: "display")
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule())
    }

    private var importWorkspace: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Bring content into AETHER").font(.title2.weight(.semibold))
                    Text("Imported paths stay explicit while renderer state remains project-persistent.")
                        .font(.callout).foregroundStyle(.secondary)
                }

                StudioPanel {
                    HStack(spacing: 20) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 18, style: .continuous)
                                .fill(Color.accentColor.opacity(0.10))
                            Image(systemName: "square.and.arrow.down")
                                .font(.system(size: 34, weight: .light)).foregroundStyle(Color.accentColor)
                        }
                        .frame(width: 82, height: 82)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Import a primary scene").font(.headline)
                            Text("AETHER and Gaussian PLY files use the Gaussian path. glTF and GLB files use the mesh/PBR renderer.")
                                .font(.callout).foregroundStyle(.secondary)
                            HStack(spacing: 6) {
                                fileTypeChip(".aether")
                                fileTypeChip(".ply")
                                fileTypeChip(".gltf")
                                fileTypeChip(".glb")
                            }
                            Button { importScene() } label: { Label("Choose Scene…", systemImage: "folder") }
                                .buttonStyle(.borderedProminent).controlSize(.large)
                        }
                        Spacer(minLength: 20)
                    }
                }

                if let scenePath = document.state.scenePath {
                    StudioPanel {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                PanelTitle(title: "Current Scene", symbol: "checkmark.circle")
                                Spacer()
                                StatusPill(text: "Loaded", symbol: "checkmark.circle.fill", color: .green)
                            }
                            LabeledContent("Name", value: URL(fileURLWithPath: scenePath).lastPathComponent)
                            LabeledContent("Renderer", value: viewportModeLabel)
                            Text(scenePath)
                                .font(.caption.monospaced()).foregroundStyle(.secondary)
                                .textSelection(.enabled).lineLimit(2)

                            if isCapturedScene {
                                Divider()
                                HStack {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text("Dynamic PBR attachment").font(.callout.weight(.medium))
                                        Text(dynamicMeshDisplayName)
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button { importDynamicMesh() } label: {
                                        Label(document.state.dynamicMeshPath == nil ? "Attach Mesh…" : "Replace…",
                                              systemImage: "cube.badge.plus")
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: 880, alignment: .leading)
        }
    }

    private func fileTypeChip(_ text: String) -> some View {
        Text(text)
            .font(.caption2.monospaced().weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.primary.opacity(0.06), in: Capsule())
    }

    @ToolbarContentBuilder
    private var studioToolbar: some ToolbarContent {
        ToolbarItemGroup {
            Button { importScene() } label: { Label("Import Scene", systemImage: "square.and.arrow.down") }
                .help("Import .aether, .ply, .gltf, or .glb")

            Menu {
                if isCapturedScene {
                    Button { importDynamicMesh() } label: {
                        Label(document.state.dynamicMeshPath == nil ? "Add Dynamic Mesh…" : "Replace Dynamic Mesh…",
                              systemImage: "cube.badge.plus")
                    }
                    if document.state.dynamicMeshPath != nil {
                        Button(role: .destructive) { removeDynamicMesh() } label: {
                            Label("Remove Dynamic Mesh", systemImage: "cube.badge.xmark")
                        }
                    }
                    Divider()
                }
                Toggle("Renderer Diagnostics", isOn: $showRendererDiagnostics)
                Divider()
                Picker("Gaussian View", selection: $gaussianDebugMode) {
                    ForEach(GaussianDebugMode.allCases) { mode in Text(mode.label).tag(mode) }
                }
                Picker("Shadow View", selection: $shadowDebugMode) {
                    ForEach(ShadowDebugMode.allCases) { mode in Text(mode.label).tag(mode) }
                }
                if shadowDebugMode != .disabled {
                    Stepper("Shadow Slice \(shadowDebugSlice)", value: $shadowDebugSlice,
                            in: 0...(shadowDebugMode == .directional ? 3 : 11))
                }
            } label: {
                Label("Viewport Options", systemImage: "slider.horizontal.3")
            }

            Button { undoManager?.undo() } label: { Image(systemName: "arrow.uturn.backward") }
                .disabled(undoManager?.canUndo != true).help("Undo")
            Button { undoManager?.redo() } label: { Image(systemName: "arrow.uturn.forward") }
                .disabled(undoManager?.canRedo != true).help("Redo")
        }
    }

    private func importScene() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = ["aether", "ply", "gltf", "glb"].compactMap { UTType(filenameExtension: $0) }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        document.state.scenePath = url.path
        document.state.dynamicMeshPath = nil
        document.state.displayName = url.deletingPathExtension().lastPathComponent
        document.state.entityTransformOverrides = [:]
        document.state.materialOverrides = [:]
        document.state.selection = AetherSelectionState()
        selection = .scene
    }

    private func importDynamicMesh() {
        guard isCapturedScene else { return }
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = ["gltf", "glb"].compactMap { UTType(filenameExtension: $0) }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        document.state.dynamicMeshPath = url.path
        document.state.entityTransformOverrides = [:]
        document.state.materialOverrides = [:]
        document.state.selection.meshEntity = nil
        document.state.selection.material = nil
        undoManager?.setActionName("Attach Dynamic Mesh")
    }

    private func removeDynamicMesh() {
        document.state.dynamicMeshPath = nil
        document.state.entityTransformOverrides = [:]
        document.state.materialOverrides = [:]
        document.state.selection.meshEntity = nil
        document.state.selection.material = nil
        selectedMeshId = nil
        selectedMaterialId = nil
    }

    private func resetRendererSelection() {
        selectedGaussianId = nil
        selectedMeshId = nil
        meshEntityNames = []
        selectedMeshTransform = nil
        selectedMaterialId = nil
        selectedMaterial = nil
        materialNames = []
    }

    private func restoreProjectUIState() {
        selection = Workspace(rawValue: document.state.selectedWorkspace) ?? .scene
        selectedMeshId = document.state.selection.meshEntity
        selectedGaussianId = document.state.selection.gaussian
        selectedMaterialId = document.state.selection.material
        selectedLightId = max(1, min(document.state.selection.light, document.state.lights.count))
        exposureStops = document.state.viewport.exposureStops
        gizmoMode = GizmoMode(rawValue: document.state.viewport.gizmoMode) ?? .translate
        gaussianDebugMode = GaussianDebugMode(rawValue: document.state.viewport.gaussianDebugMode) ?? .appearance
        shadowDebugMode = ShadowDebugMode(rawValue: document.state.viewport.shadowDebugMode) ?? .disabled
        let maximumShadowSlice = shadowDebugMode == .directional ? 3 : 11
        shadowDebugSlice = min(max(0, document.state.viewport.shadowDebugSlice), maximumShadowSlice)
    }

    private var resolvedScenePath: String? {
        guard let scenePath = document.state.scenePath else { return nil }
        if NSString(string: scenePath).isAbsolutePath { return scenePath }
        return projectURL?.deletingLastPathComponent().appendingPathComponent(scenePath).path
    }

    private var resolvedDynamicMeshPath: String? {
        guard let path = document.state.dynamicMeshPath else { return nil }
        if NSString(string: path).isAbsolutePath { return path }
        return projectURL?.deletingLastPathComponent().appendingPathComponent(path).path
    }

    private var isCapturedScene: Bool {
        guard let scenePath = document.state.scenePath else { return false }
        return ["aether", "ply"].contains(URL(fileURLWithPath: scenePath).pathExtension.lowercased())
    }

    private var dynamicMeshDisplayName: String {
        guard let path = document.state.dynamicMeshPath else { return "No mesh attachment" }
        return URL(fileURLWithPath: path).lastPathComponent
    }

    private var viewportModeLabel: String {
        guard let scenePath = document.state.scenePath else { return "AETHER FOUNDATION" }
        switch URL(fileURLWithPath: scenePath).pathExtension.lowercased() {
        case "ply", "aether":
            return document.state.dynamicMeshPath == nil ? "STANDARD GAUSSIAN GPU" : "HYBRID GAUSSIAN / DYNAMIC PBR"
        case "gltf", "glb": return "MESH / PBR"
        default: return "AETHER VIEWPORT"
        }
    }

    private var selectedTransformBinding: Binding<AetherTransformOverride> {
        Binding(
            get: { selectedMeshTransform ?? AetherTransformOverride() },
            set: { value in
                selectedMeshTransform = value
                guard let selectedMeshId else { return }
                document.state.entityTransformOverrides[String(selectedMeshId)] = value
                undoManager?.setActionName("Edit Entity Transform")
            })
    }

    private var selectedMaterialBinding: Binding<AetherMaterialOverride> {
        Binding(
            get: { selectedMaterial ?? AetherMaterialOverride() },
            set: { value in
                selectedMaterial = value
                guard let selectedMaterialId else { return }
                document.state.materialOverrides[String(selectedMaterialId)] = value
                undoManager?.setActionName("Edit Material")
            })
    }

    private var selectedLightBinding: Binding<AetherLightState> {
        Binding(
            get: {
                guard document.state.lights.indices.contains(selectedLightId - 1) else { return .defaultSun }
                return document.state.lights[selectedLightId - 1]
            },
            set: { value in
                guard document.state.lights.indices.contains(selectedLightId - 1) else { return }
                document.state.lights[selectedLightId - 1] = value
                undoManager?.setActionName("Edit Light")
            })
    }

    private func addLight() {
        guard document.state.lights.count < 4096 else { return }
        document.state.lights.append(.defaultPoint)
        selectedLightId = document.state.lights.count
        undoManager?.setActionName("Add Light")
    }

    private func removeSelectedLight() {
        guard document.state.lights.count > 1,
              document.state.lights.indices.contains(selectedLightId - 1) else { return }
        document.state.lights.remove(at: selectedLightId - 1)
        selectedLightId = min(selectedLightId, document.state.lights.count)
        undoManager?.setActionName("Remove Light")
    }
}
