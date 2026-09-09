import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

private struct WorldEditorEntityEnvelope: Decodable, Sendable {
  let schemaVersion: Int
  let available: Bool
  let revision: UInt64?
  let timestamp: UInt64?
  let entities: [WorldEditorEntity]
  let truncated: Bool?
  let totalEntities: Int?
}

private struct WorldEditorEntity: Decodable, Identifiable, Equatable, Sendable {
  let id: UInt64
  let name: String
  let semanticLabel: String
  let representation: String
  let confidence: Double
  let lastObserved: UInt64
  let geometrySignature: UInt64
  let appearanceSignature: UInt64
  let translation: [Double]
  let rotation: [Double]
  let scale: [Double]
  let boundsMinimum: [Double]
  let boundsMaximum: [Double]

  var x: Double { translation.indices.contains(0) ? translation[0] : 0 }
  var y: Double { translation.indices.contains(1) ? translation[1] : 0 }
  var z: Double { translation.indices.contains(2) ? translation[2] : 0 }
}

private struct WorldEditorDiffSummary: Decodable, Equatable, Sendable {
  let added: Int
  let removed: Int
  let modified: Int
  let unchanged: Int
  let changeRatio: Double
}

private struct WorldEditorEditReport: Decodable, Equatable, Sendable {
  let schemaVersion: Int
  let revision: UInt64
  let updatedEntities: Int
  let removedEntities: Int
  let dirtyRegionCount: Int
  let summary: WorldEditorDiffSummary
}

private final class SendableWorldEditorBridge: @unchecked Sendable {
  let value = AetherWorldBridge()
}

@MainActor
private final class WorldEntityEditorModel: ObservableObject {
  @Published var archiveURL: URL?
  @Published var entities: [WorldEditorEntity] = []
  @Published var selectedID: UInt64?
  @Published var x = 0.0
  @Published var y = 0.0
  @Published var z = 0.0
  @Published var semanticLabel = ""
  @Published var isBusy = false
  @Published var status = "Open a persistent-world archive to edit captured reality."
  @Published var errorMessage: String?
  @Published var lastEdit: WorldEditorEditReport?
  @Published var revision: UInt64?
  @Published var truncated = false
  @Published var totalEntities = 0

  private let native = SendableWorldEditorBridge()
  private var latestTimestamp: UInt64 = 0

  var selectedEntity: WorldEditorEntity? {
    guard let selectedID else { return nil }
    return entities.first(where: { $0.id == selectedID })
  }

  func chooseArchive() {
    let panel = NSOpenPanel()
    panel.title = "Open Persistent World Archive"
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    panel.allowsMultipleSelection = false
    panel.allowedContentTypes = [.json]
    guard panel.runModal() == .OK, let url = panel.url else { return }
    loadArchive(url)
  }

  func loadArchive(_ url: URL) {
    guard !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Loading persistent world…"
    let native = native

    Task {
      do {
        let envelope = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard AetherWorldLoadArchive(native.value, url, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadUnknown)
          }
          return try Self.readEntities(from: native.value)
        }.value
        archiveURL = url
        apply(envelope)
        status = "Loaded revision \(revision ?? 0) from \(url.lastPathComponent)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Persistent world load failed"
      }
      isBusy = false
    }
  }

  func select(_ id: UInt64?) {
    selectedID = id
    syncEditorFields()
  }

  func translateSelected() {
    guard let selectedID, let archiveURL, !isBusy else { return }
    let targetX = Float(x)
    let targetY = Float(y)
    let targetZ = Float(z)
    performEdit(statusText: "Moving persistent entity…") { bridge, timestamp, error in
      AetherWorldTranslateEntity(
        bridge, selectedID, targetX, targetY, targetZ, timestamp, error)
    } saveTo: archiveURL
  }

  func relabelSelected() {
    guard let selectedID, let archiveURL, !isBusy else { return }
    let label = semanticLabel
    performEdit(statusText: "Updating semantic identity…") { bridge, timestamp, error in
      AetherWorldRelabelEntity(bridge, selectedID, label, timestamp, error)
    } saveTo: archiveURL
  }

  func removeSelected() {
    guard let selectedID, let archiveURL, !isBusy else { return }
    performEdit(statusText: "Removing persistent entity…") { bridge, timestamp, error in
      AetherWorldRemoveEntity(bridge, selectedID, timestamp, error)
    } saveTo: archiveURL
  }

  func refresh() {
    guard archiveURL != nil, !isBusy else { return }
    isBusy = true
    errorMessage = nil
    let native = native
    Task {
      do {
        let envelope = try await Task.detached(priority: .utility) {
          try Self.readEntities(from: native.value)
        }.value
        apply(envelope)
        status = "Persistent entities refreshed"
      } catch {
        errorMessage = error.localizedDescription
        status = "Entity refresh failed"
      }
      isBusy = false
    }
  }

  private typealias EditOperation = @Sendable (
    AetherWorldBridge, UInt64, AutoreleasingUnsafeMutablePointer<NSError?>
  ) -> Data?

  private func performEdit(
    statusText: String,
    operation: @escaping EditOperation,
    saveTo archiveURL: URL
  ) {
    isBusy = true
    errorMessage = nil
    status = statusText
    let timestamp = nextTimestamp()
    let native = native

    Task {
      do {
        let result = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let reportData = operation(native.value, timestamp, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileWriteUnknown)
          }
          bridgeError = nil
          guard AetherWorldSaveArchive(native.value, archiveURL, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileWriteUnknown)
          }
          let report = try JSONDecoder().decode(WorldEditorEditReport.self, from: reportData)
          let envelope = try Self.readEntities(from: native.value)
          return (report, envelope)
        }.value
        lastEdit = result.0
        apply(result.1)
        status = "Committed and saved world revision \(result.0.revision)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Persistent world edit failed"
      }
      isBusy = false
    }
  }

  private func nextTimestamp() -> UInt64 {
    let wallClockSeconds = max(0, Date().timeIntervalSince1970)
    let wallClock = UInt64(wallClockSeconds * 1_000_000_000.0)
    let sequenceFloor = latestTimestamp == UInt64.max ? UInt64.max : latestTimestamp + 1
    let timestamp = max(wallClock, sequenceFloor)
    latestTimestamp = timestamp
    return timestamp
  }

  private func apply(_ envelope: WorldEditorEntityEnvelope) {
    revision = envelope.revision
    latestTimestamp = max(latestTimestamp, envelope.timestamp ?? 0)
    entities = envelope.entities
    truncated = envelope.truncated ?? false
    totalEntities = envelope.totalEntities ?? envelope.entities.count

    if let selectedID, entities.contains(where: { $0.id == selectedID }) {
      self.selectedID = selectedID
    } else {
      selectedID = entities.first?.id
    }
    syncEditorFields()
  }

  private func syncEditorFields() {
    guard let entity = selectedEntity else {
      x = 0
      y = 0
      z = 0
      semanticLabel = ""
      return
    }
    x = entity.x
    y = entity.y
    z = entity.z
    semanticLabel = entity.semanticLabel
  }

  nonisolated private static func readEntities(
    from bridge: AetherWorldBridge
  ) throws -> WorldEditorEntityEnvelope {
    var bridgeError: NSError?
    guard let data = AetherWorldLatestEntitiesJSON(bridge, &bridgeError) else {
      throw bridgeError ?? CocoaError(.fileReadCorruptFile)
    }
    return try JSONDecoder().decode(WorldEditorEntityEnvelope.self, from: data)
  }
}

struct WorldEntityEditorWindow: View {
  @StateObject private var model = WorldEntityEditorModel()

  var body: some View {
    NavigationSplitView {
      entityList
    } detail: {
      inspector
    }
    .navigationSplitViewStyle(.balanced)
    .frame(minWidth: 960, minHeight: 640)
    .toolbar {
      ToolbarItemGroup {
        Button("Open World…", systemImage: "folder", action: model.chooseArchive)
        Button("Refresh", systemImage: "arrow.clockwise", action: model.refresh)
          .disabled(model.archiveURL == nil || model.isBusy)
      }
    }
  }

  private var entityList: some View {
    VStack(spacing: 0) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text("WORLD ENTITIES")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .tracking(0.8)
          if let revision = model.revision {
            Text("Revision \(revision)")
              .font(.caption.monospacedDigit())
              .foregroundStyle(.tertiary)
          }
        }
        Spacer()
        if model.isBusy { ProgressView().controlSize(.small) }
      }
      .padding(14)

      Divider()

      if model.entities.isEmpty {
        ContentUnavailableView(
          "No Persistent Entities",
          systemImage: "cube.transparent",
          description: Text("Open a world archive containing at least one committed revision."))
      } else {
        List(selection: Binding(get: { model.selectedID }, set: model.select)) {
          ForEach(model.entities) { entity in
            VStack(alignment: .leading, spacing: 3) {
              HStack {
                Text(entity.name.isEmpty ? "Entity #\(entity.id)" : entity.name)
                  .lineLimit(1)
                Spacer()
                Text("#\(entity.id)")
                  .font(.caption2.monospacedDigit())
                  .foregroundStyle(.tertiary)
              }
              HStack(spacing: 7) {
                Text(entity.semanticLabel.isEmpty ? "unlabeled" : entity.semanticLabel)
                Text("•")
                Text(entity.representation)
                Text("•")
                Text(entity.confidence.formatted(.percent.precision(.fractionLength(0))))
              }
              .font(.caption)
              .foregroundStyle(.secondary)
            }
            .tag(entity.id)
          }
        }
        .listStyle(.sidebar)
      }

      if model.truncated {
        Divider()
        Label(
          "Showing \(model.entities.count) of \(model.totalEntities)",
          systemImage: "ellipsis.circle")
          .font(.caption)
          .foregroundStyle(.secondary)
          .padding(10)
      }
    }
    .navigationSplitViewColumnWidth(min: 260, ideal: 320, max: 420)
  }

  private var inspector: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        header
        if let errorMessage = model.errorMessage {
          editorCard {
            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
              .foregroundStyle(.red)
          }
        }
        if let entity = model.selectedEntity {
          transformCard(entity)
          semanticsCard(entity)
          metadataCard(entity)
          destructiveCard(entity)
        } else {
          ContentUnavailableView(
            "Select an Entity",
            systemImage: "cursorarrow.click",
            description: Text("Choose a stable persistent entity from the world list."))
            .frame(maxWidth: .infinity, minHeight: 360)
        }
      }
      .padding(24)
      .frame(maxWidth: 820, alignment: .leading)
    }
    .background(Color(nsColor: .windowBackgroundColor))
  }

  private var header: some View {
    HStack(spacing: 12) {
      ZStack {
        RoundedRectangle(cornerRadius: 12, style: .continuous)
          .fill(Color.accentColor.opacity(0.12))
        Image(systemName: "move.3d")
          .foregroundStyle(Color.accentColor)
      }
      .frame(width: 48, height: 48)

      VStack(alignment: .leading, spacing: 3) {
        Text("Persistent Entity Editor")
          .font(.title2.weight(.semibold))
        Text(model.status)
          .font(.callout)
          .foregroundStyle(.secondary)
      }
      Spacer()
    }
  }

  private func transformCard(_ entity: WorldEditorEntity) -> some View {
    editorCard {
      VStack(alignment: .leading, spacing: 14) {
        editorSectionTitle("Metric transform", symbol: "move.3d")
        Text(
          "Translation edits create a new immutable world revision and dirty both the previous and new spatial extent."
        )
        .font(.caption)
        .foregroundStyle(.secondary)

        HStack(spacing: 8) {
          coordinateField("X", value: $model.x)
          coordinateField("Y", value: $model.y)
          coordinateField("Z", value: $model.z)
        }

        HStack {
          Text(
            "Current: (\(entity.x.formatted(.number.precision(.fractionLength(3)))), \(entity.y.formatted(.number.precision(.fractionLength(3)))), \(entity.z.formatted(.number.precision(.fractionLength(3))))) m"
          )
          .font(.caption.monospacedDigit())
          .foregroundStyle(.secondary)
          Spacer()
          Button("Commit Move", systemImage: "checkmark.circle", action: model.translateSelected)
            .buttonStyle(.borderedProminent)
            .disabled(model.isBusy)
        }
      }
    }
  }

  private func semanticsCard(_ entity: WorldEditorEntity) -> some View {
    editorCard {
      VStack(alignment: .leading, spacing: 12) {
        editorSectionTitle("Semantic identity", symbol: "tag")
        TextField("Semantic label", text: $model.semanticLabel)
          .textFieldStyle(.roundedBorder)
        HStack {
          Text("Current label: \(entity.semanticLabel.isEmpty ? "unlabeled" : entity.semanticLabel)")
            .font(.caption)
            .foregroundStyle(.secondary)
          Spacer()
          Button("Commit Label", systemImage: "tag.fill", action: model.relabelSelected)
            .disabled(model.isBusy)
        }
      }
    }
  }

  private func metadataCard(_ entity: WorldEditorEntity) -> some View {
    editorCard {
      VStack(alignment: .leading, spacing: 12) {
        editorSectionTitle("Persistent state", symbol: "info.circle")
        LabeledContent("Stable ID", value: "\(entity.id)")
        LabeledContent("Representation", value: entity.representation)
        LabeledContent(
          "Confidence",
          value: entity.confidence.formatted(.percent.precision(.fractionLength(1))))
        LabeledContent("Geometry signature", value: String(entity.geometrySignature, radix: 16))
        LabeledContent("Appearance signature", value: String(entity.appearanceSignature, radix: 16))
        if let lastEdit = model.lastEdit {
          Divider()
          LabeledContent("Last authored revision", value: "\(lastEdit.revision)")
          LabeledContent("Dirty regions", value: "\(lastEdit.dirtyRegionCount)")
        }
      }
      .font(.callout)
    }
  }

  private func destructiveCard(_ entity: WorldEditorEntity) -> some View {
    editorCard {
      HStack {
        VStack(alignment: .leading, spacing: 3) {
          Text("Remove from persistent world")
            .font(.callout.weight(.medium))
          Text(
            "Entity #\(entity.id) is removed in a new revision; earlier revisions remain intact and diffable."
          )
          .font(.caption)
          .foregroundStyle(.secondary)
        }
        Spacer()
        Button(
          "Remove Entity", systemImage: "trash", role: .destructive,
          action: model.removeSelected)
          .disabled(model.isBusy)
      }
    }
  }

  private func coordinateField(_ label: String, value: Binding<Double>) -> some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(label)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      TextField(label, value: value, format: .number.precision(.fractionLength(4)))
        .textFieldStyle(.roundedBorder)
        .font(.body.monospacedDigit())
    }
  }

  private func editorSectionTitle(_ title: String, symbol: String) -> some View {
    Label(title.uppercased(), systemImage: symbol)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(.secondary)
      .tracking(0.7)
  }

  private func editorCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
    content()
      .padding(16)
      .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 14, style: .continuous)
          .stroke(Color.primary.opacity(0.08), lineWidth: 1)
      }
  }
}
