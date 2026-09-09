import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

private struct LiveRealityEntityEnvelope: Decodable {
  let schemaVersion: Int
  let available: Bool
  let revision: UInt64?
  let timestamp: UInt64?
  let entities: [LiveRealityEntity]
  let truncated: Bool?
  let totalEntities: Int?
  let gaussianStateLoaded: Bool?
}

private struct LiveRealityEntity: Decodable, Identifiable, Equatable {
  let id: UInt64
  let name: String
  let semanticLabel: String
  let representation: String
  let confidence: Double
  let translation: [Double]

  var x: Double { translation.indices.contains(0) ? translation[0] : 0 }
  var y: Double { translation.indices.contains(1) ? translation[1] : 0 }
  var z: Double { translation.indices.contains(2) ? translation[2] : 0 }
}

private struct LiveRealityOwnershipReport: Decodable, Equatable {
  let schemaVersion: Int
  let available: Bool
  let gaussianCount: Int?
  let assigned: Int?
  let unassigned: Int?
  let coverage: Double?
}

private struct LiveRealityEditReport: Decodable, Equatable {
  let schemaVersion: Int
  let revision: UInt64
  let translatedGaussians: Int
  let reoptimizationGaussians: Int
  let protectedStableGaussians: Int
  let conservativeBoundaryGaussians: Int
  let dirtyRegionCount: Int
  let persisted: Bool
  let persistenceError: String
}

@MainActor
private final class LivePersistentRealityModel: ObservableObject {
  let viewport = AetherPersistentGaussianView(frame: .zero)

  @Published var archiveURL: URL?
  @Published var entities: [LiveRealityEntity] = []
  @Published var selectedID: UInt64?
  @Published var x = 0.0
  @Published var y = 0.0
  @Published var z = 0.0
  @Published var revision: UInt64?
  @Published var ownership: LiveRealityOwnershipReport?
  @Published var lastEdit: LiveRealityEditReport?
  @Published var status = "Open a persistent world archive, then import or restore its Gaussian field."
  @Published var errorMessage: String?
  @Published var isBusy = false
  @Published var gaussianStateLoaded = false
  @Published var truncated = false
  @Published var totalEntities = 0

  private var latestTimestamp: UInt64 = 0

  var selectedEntity: LiveRealityEntity? {
    guard let selectedID else { return nil }
    return entities.first(where: { $0.id == selectedID })
  }

  init() {
    viewport.preferredFramesPerSecond = 60
  }

  func chooseWorldArchive() {
    guard !isBusy else { return }
    let panel = NSOpenPanel()
    panel.title = "Open Persistent World"
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    panel.allowsMultipleSelection = false
    panel.allowedContentTypes = [.json]
    guard panel.runModal() == .OK, let url = panel.url else { return }
    loadWorldArchive(url)
  }

  func chooseGaussianPLY() {
    guard archiveURL != nil, !isBusy else { return }
    let panel = NSOpenPanel()
    panel.title = "Import Gaussian Field"
    panel.message = "Choose the source-order 3D Gaussian PLY corresponding to this persistent world."
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    panel.allowsMultipleSelection = false
    panel.allowedContentTypes = [UTType(filenameExtension: "ply") ?? .data]
    guard panel.runModal() == .OK, let url = panel.url else { return }
    importGaussianPLY(url)
  }

  func loadWorldArchive(_ url: URL) {
    guard !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Loading persistent world and revision-matched Gaussian state…"

    var bridgeError: NSError?
    if AetherPersistentLoadWorld(viewport, url, &bridgeError) {
      archiveURL = url
      refreshNativeState()
      status = gaussianStateLoaded
        ? "Loaded live persistent revision \(revision ?? 0)"
        : "Loaded revision \(revision ?? 0). Import a Gaussian PLY to enable live captured-object edits."
    } else {
      errorMessage = bridgeError?.localizedDescription ?? "Persistent world could not be loaded."
      status = "Persistent world load failed"
    }
    isBusy = false
  }

  func importGaussianPLY(_ url: URL) {
    guard archiveURL != nil, !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Loading Gaussian field and assigning persistent ownership…"

    var bridgeError: NSError?
    if AetherPersistentLoadGaussianPLY(viewport, url, &bridgeError) {
      refreshNativeState()
      status = "Gaussian field loaded, ownership assigned, and persistent sidecars saved"
    } else {
      errorMessage = bridgeError?.localizedDescription ?? "Gaussian field import failed."
      status = "Gaussian field import failed"
    }
    isBusy = false
  }

  func save() {
    guard gaussianStateLoaded, !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Saving persistent visual state…"

    var bridgeError: NSError?
    if AetherPersistentSaveState(viewport, &bridgeError) {
      status = "Persistent world, Gaussian field, and ownership saved"
    } else {
      errorMessage = bridgeError?.localizedDescription ?? "Persistent visual state could not be saved."
      status = "Persistent save failed"
    }
    isBusy = false
  }

  func select(_ id: UInt64?) {
    selectedID = id
    syncEditorFields()
  }

  func translateSelected() {
    guard let selectedID, gaussianStateLoaded, !isBusy else { return }
    let targetX = Float(x)
    let targetY = Float(y)
    let targetZ = Float(z)
    let timestamp = nextTimestamp()

    isBusy = true
    errorMessage = nil
    status = "Committing World + Gaussian + Metal translation…"
    var bridgeError: NSError?
    guard let data = AetherPersistentTranslateEntity(
      viewport, selectedID, targetX, targetY, targetZ, timestamp, &bridgeError)
    else {
      errorMessage = bridgeError?.localizedDescription ?? "Live persistent translation failed."
      status = "Live translation failed without committing a visual edit"
      isBusy = false
      return
    }

    do {
      let report = try JSONDecoder().decode(LiveRealityEditReport.self, from: data)
      lastEdit = report
      refreshNativeState()
      if report.persisted {
        status = "Revision \(report.revision) committed, rendered live, and persisted"
      } else {
        errorMessage = report.persistenceError.isEmpty
          ? "The edit is live in memory but persistent sidecar publication failed."
          : report.persistenceError
        status = "Revision \(report.revision) is live; save retry required"
      }
    } catch {
      errorMessage = error.localizedDescription
      status = "Live edit committed, but Studio could not decode its report"
    }
    isBusy = false
  }

  func refresh() {
    guard archiveURL != nil, !isBusy else { return }
    refreshNativeState()
    status = "Live persistent state refreshed"
  }

  private func refreshNativeState() {
    var bridgeError: NSError?
    guard let entityData = AetherPersistentEntitiesJSON(viewport, &bridgeError) else {
      errorMessage = bridgeError?.localizedDescription ?? "Could not read persistent entities."
      return
    }

    do {
      let envelope = try JSONDecoder().decode(LiveRealityEntityEnvelope.self, from: entityData)
      revision = envelope.revision
      latestTimestamp = max(latestTimestamp, envelope.timestamp ?? 0)
      entities = envelope.entities
      gaussianStateLoaded = envelope.gaussianStateLoaded ?? false
      truncated = envelope.truncated ?? false
      totalEntities = envelope.totalEntities ?? envelope.entities.count

      if let selectedID, entities.contains(where: { $0.id == selectedID }) {
        self.selectedID = selectedID
      } else {
        selectedID = entities.first?.id
      }
      syncEditorFields()
    } catch {
      errorMessage = error.localizedDescription
    }

    bridgeError = nil
    if let ownershipData = AetherPersistentOwnershipJSON(viewport, &bridgeError) {
      do {
        ownership = try JSONDecoder().decode(LiveRealityOwnershipReport.self, from: ownershipData)
      } catch {
        errorMessage = error.localizedDescription
      }
    } else if let bridgeError {
      errorMessage = bridgeError.localizedDescription
    }
  }

  private func syncEditorFields() {
    guard let entity = selectedEntity else {
      x = 0
      y = 0
      z = 0
      return
    }
    x = entity.x
    y = entity.y
    z = entity.z
  }

  private func nextTimestamp() -> UInt64 {
    let wallClockSeconds = max(0, Date().timeIntervalSince1970)
    let wallClock = UInt64(wallClockSeconds * 1_000_000_000.0)
    let sequenceFloor = latestTimestamp == UInt64.max ? UInt64.max : latestTimestamp + 1
    let result = max(wallClock, sequenceFloor)
    latestTimestamp = result
    return result
  }
}

private struct LivePersistentMetalViewport: NSViewRepresentable {
  let viewport: AetherPersistentGaussianView

  func makeNSView(context: Context) -> AetherPersistentGaussianView {
    viewport
  }

  func updateNSView(_ nsView: AetherPersistentGaussianView, context: Context) {
    nsView.preferredFramesPerSecond = 60
  }
}

struct LivePersistentRealityEditor: View {
  @StateObject private var model = LivePersistentRealityModel()

  var body: some View {
    VStack(spacing: 0) {
      topBar
      Divider()
      HSplitView {
        viewportPane
          .frame(minWidth: 640)
        inspectorPane
          .frame(minWidth: 330, idealWidth: 390, maxWidth: 480)
      }
    }
    .frame(minWidth: 1120, minHeight: 760)
  }

  private var topBar: some View {
    HStack(spacing: 10) {
      Image(systemName: "cube.transparent.fill")
        .foregroundStyle(Color.accentColor)
      VStack(alignment: .leading, spacing: 2) {
        Text("Live Persistent Reality")
          .font(.headline)
        Text(model.status)
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(1)
      }
      Spacer()
      if model.isBusy {
        ProgressView()
          .controlSize(.small)
      }
      Button("Open World…", systemImage: "folder", action: model.chooseWorldArchive)
      Button("Import PLY…", systemImage: "point.3.connected.trianglepath.dotted", action: model.chooseGaussianPLY)
        .disabled(model.archiveURL == nil || model.isBusy)
      Button("Save", systemImage: "square.and.arrow.down", action: model.save)
        .disabled(!model.gaussianStateLoaded || model.isBusy)
    }
    .padding(.horizontal, 14)
    .padding(.vertical, 10)
    .background(.bar)
  }

  private var viewportPane: some View {
    ZStack(alignment: .topLeading) {
      LivePersistentMetalViewport(viewport: model.viewport)
        .background(Color.black)

      VStack(alignment: .leading, spacing: 5) {
        Label("LIVE METAL", systemImage: "sparkles.rectangle.stack")
          .font(.caption2.weight(.bold))
          .tracking(0.7)
        Text(model.viewport.rendererStatus)
          .font(.caption2)
          .foregroundStyle(.secondary)
        if let revision = model.revision {
          Text("Persistent revision \(revision)")
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
      }
      .padding(10)
      .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .padding(12)
    }
  }

  private var inspectorPane: some View {
    VStack(spacing: 0) {
      diagnosticsHeader
      Divider()
      entityList
      Divider()
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
          if let errorMessage = model.errorMessage {
            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
              .font(.caption)
              .foregroundStyle(.red)
              .frame(maxWidth: .infinity, alignment: .leading)
              .padding(10)
              .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
          }

          if let entity = model.selectedEntity {
            transformEditor(entity)
            lastEditCard
          } else {
            ContentUnavailableView(
              "Select an Entity",
              systemImage: "cursorarrow.click",
              description: Text("Choose a stable entity whose owned Gaussian field you want to move."))
          }
        }
        .padding(14)
      }
    }
    .background(Color(nsColor: .controlBackgroundColor))
  }

  private var diagnosticsHeader: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Text("GAUSSIAN OWNERSHIP")
          .font(.caption2.weight(.bold))
          .tracking(0.7)
          .foregroundStyle(.secondary)
        Spacer()
        Button(action: model.refresh) {
          Image(systemName: "arrow.clockwise")
        }
        .buttonStyle(.plain)
        .disabled(model.archiveURL == nil || model.isBusy)
      }

      if let ownership = model.ownership, ownership.available {
        HStack(spacing: 14) {
          metric("Splats", ownership.gaussianCount ?? 0)
          metric("Owned", ownership.assigned ?? 0)
          metric("Unowned", ownership.unassigned ?? 0)
        }
        if let coverage = ownership.coverage {
          ProgressView(value: coverage)
          Text("\(coverage.formatted(.percent.precision(.fractionLength(1)))) stable-entity ownership coverage")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      } else {
        Text("Import a Gaussian PLY to create persistent entity ownership.")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
    }
    .padding(14)
  }

  private var entityList: some View {
    Group {
      if model.entities.isEmpty {
        ContentUnavailableView(
          "No World Entities",
          systemImage: "cube",
          description: Text("Open a persistent world archive first."))
          .frame(minHeight: 180)
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
              HStack(spacing: 5) {
                Text(entity.semanticLabel.isEmpty ? "unlabeled" : entity.semanticLabel)
                Text("•")
                Text(entity.representation)
                Text("•")
                Text(entity.confidence.formatted(.percent.precision(.fractionLength(0))))
              }
              .font(.caption2)
              .foregroundStyle(.secondary)
            }
            .tag(entity.id)
          }
        }
        .listStyle(.inset)
        .frame(minHeight: 210, idealHeight: 280)
      }
    }
  }

  private func transformEditor(_ entity: LiveRealityEntity) -> some View {
    GroupBox("Live metric translation") {
      VStack(alignment: .leading, spacing: 12) {
        Text(
          "Commits a new persistent revision, moves only splats owned by this stable entity, protects neighboring stable splats, refreshes Metal, and saves revision-addressed sidecars."
        )
        .font(.caption)
        .foregroundStyle(.secondary)

        HStack(spacing: 7) {
          coordinateField("X", value: $model.x)
          coordinateField("Y", value: $model.y)
          coordinateField("Z", value: $model.z)
        }

        Text(
          "Current: (\(entity.x.formatted(.number.precision(.fractionLength(3)))), \(entity.y.formatted(.number.precision(.fractionLength(3)))), \(entity.z.formatted(.number.precision(.fractionLength(3))))) m"
        )
        .font(.caption2.monospacedDigit())
        .foregroundStyle(.secondary)

        Button("Commit Live Move", systemImage: "move.3d", action: model.translateSelected)
          .buttonStyle(.borderedProminent)
          .frame(maxWidth: .infinity, alignment: .trailing)
          .disabled(!model.gaussianStateLoaded || model.isBusy)
      }
      .padding(.vertical, 4)
    }
  }

  @ViewBuilder
  private var lastEditCard: some View {
    if let edit = model.lastEdit {
      GroupBox("Last live transaction") {
        VStack(alignment: .leading, spacing: 7) {
          LabeledContent("Revision", value: "\(edit.revision)")
          LabeledContent("Translated splats", value: "\(edit.translatedGaussians)")
          LabeledContent("Local re-optimization set", value: "\(edit.reoptimizationGaussians)")
          LabeledContent("Stable splats protected", value: "\(edit.protectedStableGaussians)")
          LabeledContent("Boundary splats", value: "\(edit.conservativeBoundaryGaussians)")
          LabeledContent("Dirty metric regions", value: "\(edit.dirtyRegionCount)")
          LabeledContent("Durable", value: edit.persisted ? "yes" : "retry required")
        }
        .font(.caption)
        .padding(.vertical, 4)
      }
    }
  }

  private func coordinateField(_ title: String, value: Binding<Double>) -> some View {
    VStack(alignment: .leading, spacing: 3) {
      Text(title)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      TextField(title, value: value, format: .number.precision(.fractionLength(4)))
        .textFieldStyle(.roundedBorder)
    }
  }

  private func metric(_ title: String, _ value: Int) -> some View {
    VStack(alignment: .leading, spacing: 1) {
      Text(value.formatted())
        .font(.callout.monospacedDigit().weight(.semibold))
      Text(title)
        .font(.caption2)
        .foregroundStyle(.secondary)
    }
  }
}
