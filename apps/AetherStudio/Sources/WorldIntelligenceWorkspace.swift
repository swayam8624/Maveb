import AppKit
import Foundation
import SwiftUI

private struct IntelligenceEntity: Decodable, Identifiable, Equatable {
  let id: UInt64
  let name: String
  let semanticLabel: String
}

private struct SemanticQueryEnvelope: Decodable {
  let schemaVersion: Int
  let revision: UInt64
  let semanticLabel: String
  let entities: [IntelligenceEntity]
}

private struct NearestQueryHit: Decodable, Identifiable, Equatable {
  let id: UInt64
  let name: String
  let semanticLabel: String
  let pointToBoundsMeters: Double
  let centerDistanceMeters: Double
}

private struct NearestQueryEnvelope: Decodable {
  let schemaVersion: Int
  let revision: UInt64
  let queryPoint: [Double]
  let semanticLabel: String
  let results: [NearestQueryHit]
}

private struct RelationsQueryEnvelope: Decodable, Equatable {
  let schemaVersion: Int
  let revision: UInt64
  let subject: IntelligenceEntity
  let reference: IntelligenceEntity
  let centerDistanceMeters: Double
  let boundsSeparationMeters: Double
  let intersects: Bool
  let subjectContainsReference: Bool
  let subjectInsideReference: Bool
  let near: Bool
}

private final class SendableIntelligenceBridge: @unchecked Sendable {
  let value = AetherWorldBridge()
}

@MainActor
private final class WorldIntelligenceModel: ObservableObject {
  @Published var archiveURL: URL?
  @Published var status = "Open a persistent-world archive to query spatial reality."
  @Published var errorMessage: String?
  @Published var isBusy = false

  @Published var semanticLabel = "chair"
  @Published var semanticResults: [IntelligenceEntity] = []
  @Published var semanticRevision: UInt64?

  @Published var pointX = 0.0
  @Published var pointY = 0.0
  @Published var pointZ = 0.0
  @Published var nearestSemanticLabel = ""
  @Published var maximumDistance = 10.0
  @Published var nearestResults: [NearestQueryHit] = []
  @Published var nearestRevision: UInt64?

  @Published var subjectID = ""
  @Published var referenceID = ""
  @Published var nearThreshold = 1.0
  @Published var relations: RelationsQueryEnvelope?

  private let native = SendableIntelligenceBridge()

  var hasWorld: Bool { archiveURL != nil }

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
        try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard AetherWorldLoadArchive(native.value, url, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadUnknown)
          }
        }.value
        archiveURL = url
        semanticResults = []
        nearestResults = []
        relations = nil
        status = "World intelligence ready • \(url.lastPathComponent)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Persistent world load failed"
      }
      isBusy = false
    }
  }

  func runSemanticQuery() {
    guard hasWorld, !isBusy else { return }
    let label = semanticLabel.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !label.isEmpty else {
      errorMessage = "Enter an exact semantic label such as chair, desk, wall, or lamp."
      return
    }
    isBusy = true
    errorMessage = nil
    status = "Searching semantic world index…"
    let native = native

    Task {
      do {
        let envelope = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let data = AetherWorldSemanticEntities(native.value, label, 500, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadCorruptFile)
          }
          return try JSONDecoder().decode(SemanticQueryEnvelope.self, from: data)
        }.value
        semanticResults = envelope.entities
        semanticRevision = envelope.revision
        status = "Found \(envelope.entities.count) ‘\(label)’ entities in r\(envelope.revision)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Semantic query failed"
      }
      isBusy = false
    }
  }

  func runNearestQuery() {
    guard hasWorld, !isBusy else { return }
    let label = nearestSemanticLabel.trimmingCharacters(in: .whitespacesAndNewlines)
    let x = pointX
    let y = pointY
    let z = pointZ
    let distance = maximumDistance
    guard distance.isFinite, distance >= 0 else {
      errorMessage = "Maximum distance must be finite and non-negative."
      return
    }
    isBusy = true
    errorMessage = nil
    status = "Querying nearest persistent entities…"
    let native = native

    Task {
      do {
        let envelope = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let data = AetherWorldNearestEntities(
            native.value, Float(x), Float(y), Float(z), label, Float(distance), 100, &bridgeError)
          else {
            throw bridgeError ?? CocoaError(.fileReadCorruptFile)
          }
          return try JSONDecoder().decode(NearestQueryEnvelope.self, from: data)
        }.value
        nearestResults = envelope.results
        nearestRevision = envelope.revision
        status = "Nearest query returned \(envelope.results.count) entities in r\(envelope.revision)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Nearest query failed"
      }
      isBusy = false
    }
  }

  func runRelationsQuery() {
    guard hasWorld, !isBusy else { return }
    guard let subject = UInt64(subjectID), let reference = UInt64(referenceID) else {
      errorMessage = "Subject and reference must be valid persistent entity IDs."
      return
    }
    let threshold = nearThreshold
    guard threshold.isFinite, threshold >= 0 else {
      errorMessage = "Near threshold must be finite and non-negative."
      return
    }
    isBusy = true
    errorMessage = nil
    status = "Computing spatial relations…"
    let native = native

    Task {
      do {
        let envelope = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let data = AetherWorldRelations(
            native.value, subject, reference, Float(threshold), &bridgeError)
          else {
            throw bridgeError ?? CocoaError(.fileReadCorruptFile)
          }
          return try JSONDecoder().decode(RelationsQueryEnvelope.self, from: data)
        }.value
        relations = envelope
        status = "Spatial relation computed in r\(envelope.revision)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Spatial relation query failed"
      }
      isBusy = false
    }
  }
}

private struct IntelligenceCard<Content: View>: View {
  let content: Content

  init(@ViewBuilder content: () -> Content) {
    self.content = content()
  }

  var body: some View {
    content
      .padding(18)
      .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 16, style: .continuous)
          .stroke(Color.primary.opacity(0.08), lineWidth: 1)
      }
  }
}

struct WorldIntelligenceWorkspace: View {
  @StateObject private var model = WorldIntelligenceModel()

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        hero
        worldCard
        if let errorMessage = model.errorMessage { errorCard(errorMessage) }
        semanticCard
        nearestCard
        relationsCard
      }
      .padding(28)
      .frame(maxWidth: 1160, alignment: .leading)
    }
    .background(Color(nsColor: .windowBackgroundColor))
  }

  private var hero: some View {
    HStack(spacing: 16) {
      ZStack {
        RoundedRectangle(cornerRadius: 18, style: .continuous)
          .fill(Color.accentColor.opacity(0.12))
        Image(systemName: "point.3.filled.connected.trianglepath.dotted")
          .font(.system(size: 29, weight: .light))
          .foregroundStyle(Color.accentColor)
      }
      .frame(width: 72, height: 72)

      VStack(alignment: .leading, spacing: 5) {
        Text("World Intelligence")
          .font(.title2.weight(.semibold))
        Text(
          "Deterministic semantic and spatial queries over the latest committed persistent-world revision. Results come from native world geometry, not language-model guesses."
        )
        .font(.callout)
        .foregroundStyle(.secondary)
        .frame(maxWidth: 760, alignment: .leading)
        Label(model.status, systemImage: model.hasWorld ? "checkmark.seal.fill" : "circle.dashed")
          .font(.caption.weight(.medium))
          .foregroundStyle(model.hasWorld ? Color.green : Color.secondary)
      }
      Spacer()
      if model.isBusy { ProgressView().controlSize(.small) }
    }
  }

  private var worldCard: some View {
    IntelligenceCard {
      HStack(spacing: 12) {
        VStack(alignment: .leading, spacing: 3) {
          Label("Persistent world", systemImage: "externaldrive.badge.timemachine")
            .font(.headline)
          Text(model.archiveURL?.path ?? "No archive loaded")
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .truncationMode(.middle)
        }
        Spacer()
        Button("Open World…", systemImage: "folder", action: model.chooseArchive)
          .buttonStyle(.borderedProminent)
          .disabled(model.isBusy)
      }
    }
  }

  private var semanticCard: some View {
    IntelligenceCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionTitle("Semantic lookup", symbol: "tag")
        Text("Find all entities whose committed semantic label exactly matches the query.")
          .font(.caption)
          .foregroundStyle(.secondary)

        HStack {
          TextField("chair", text: $model.semanticLabel)
            .textFieldStyle(.roundedBorder)
          Button("Find Entities", systemImage: "magnifyingglass", action: model.runSemanticQuery)
            .buttonStyle(.borderedProminent)
            .disabled(!model.hasWorld || model.isBusy)
        }

        if let revision = model.semanticRevision {
          Text("Result revision: r\(revision)")
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }

        if !model.semanticResults.isEmpty {
          LazyVStack(spacing: 7) {
            ForEach(model.semanticResults) { entity in
              compactEntityRow(entity)
            }
          }
        }
      }
    }
  }

  private var nearestCard: some View {
    IntelligenceCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionTitle("Nearest to metric point", symbol: "scope")
        Text(
          "Distances are measured to each entity’s world-space AABB surface, so large objects are not misranked by distant centers. Leave semantic label empty to search all entities."
        )
        .font(.caption)
        .foregroundStyle(.secondary)

        HStack(spacing: 8) {
          coordinateField("X", value: $model.pointX)
          coordinateField("Y", value: $model.pointY)
          coordinateField("Z", value: $model.pointZ)
          coordinateField("Max m", value: $model.maximumDistance)
        }
        HStack {
          TextField("Optional semantic label", text: $model.nearestSemanticLabel)
            .textFieldStyle(.roundedBorder)
          Button("Find Nearest", systemImage: "location.magnifyingglass", action: model.runNearestQuery)
            .buttonStyle(.borderedProminent)
            .disabled(!model.hasWorld || model.isBusy)
        }

        if let revision = model.nearestRevision {
          Text("Result revision: r\(revision)")
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }

        if !model.nearestResults.isEmpty {
          LazyVStack(spacing: 7) {
            ForEach(model.nearestResults) { hit in
              HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                  Text(hit.name.isEmpty ? "Entity #\(hit.id)" : hit.name)
                    .font(.callout.weight(.medium))
                  Text(hit.semanticLabel.isEmpty ? "unlabeled" : hit.semanticLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                  Text("\(hit.pointToBoundsMeters.formatted(.number.precision(.fractionLength(3)))) m")
                    .font(.callout.monospacedDigit().weight(.semibold))
                  Text("surface distance")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
              }
              .padding(10)
              .background(
                Color.primary.opacity(0.04),
                in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
          }
        }
      }
    }
  }

  private var relationsCard: some View {
    IntelligenceCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionTitle("Entity relations", symbol: "arrow.left.and.right.righttriangle.left.righttriangle.right")
        Text(
          "Compute geometric relations between two stable IDs: intersection, containment, surface separation, center distance, and configurable nearness."
        )
        .font(.caption)
        .foregroundStyle(.secondary)

        HStack(spacing: 8) {
          TextField("Subject ID", text: $model.subjectID)
            .textFieldStyle(.roundedBorder)
          TextField("Reference ID", text: $model.referenceID)
            .textFieldStyle(.roundedBorder)
          coordinateField("Near m", value: $model.nearThreshold)
          Button("Compute", systemImage: "arrow.left.arrow.right", action: model.runRelationsQuery)
            .buttonStyle(.borderedProminent)
            .disabled(!model.hasWorld || model.isBusy)
        }

        if let relation = model.relations {
          HStack(spacing: 10) {
            relationMetric("Surface", relation.boundsSeparationMeters, suffix: "m")
            relationMetric("Centers", relation.centerDistanceMeters, suffix: "m")
            booleanMetric("Near", relation.near)
            booleanMetric("Intersect", relation.intersects)
            booleanMetric("Contains", relation.subjectContainsReference)
            booleanMetric("Inside", relation.subjectInsideReference)
          }
          Text(
            "#\(relation.subject.id) \(relation.subject.name)  →  #\(relation.reference.id) \(relation.reference.name)"
          )
          .font(.caption.monospacedDigit())
          .foregroundStyle(.secondary)
        }
      }
    }
  }

  private func sectionTitle(_ title: String, symbol: String) -> some View {
    Label(title, systemImage: symbol)
      .font(.headline)
  }

  private func compactEntityRow(_ entity: IntelligenceEntity) -> some View {
    HStack {
      VStack(alignment: .leading, spacing: 2) {
        Text(entity.name.isEmpty ? "Entity #\(entity.id)" : entity.name)
          .font(.callout.weight(.medium))
        Text(entity.semanticLabel.isEmpty ? "unlabeled" : entity.semanticLabel)
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      Spacer()
      Text("#\(entity.id)")
        .font(.caption.monospacedDigit())
        .foregroundStyle(.secondary)
    }
    .padding(10)
    .background(
      Color.primary.opacity(0.04),
      in: RoundedRectangle(cornerRadius: 10, style: .continuous))
  }

  private func coordinateField(_ label: String, value: Binding<Double>) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(label.uppercased())
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      TextField(label, value: value, format: .number.precision(.fractionLength(3)))
        .textFieldStyle(.roundedBorder)
        .frame(minWidth: 90)
    }
  }

  private func relationMetric(_ label: String, _ value: Double, suffix: String) -> some View {
    VStack(alignment: .leading, spacing: 3) {
      Text(label.uppercased())
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      Text("\(value.formatted(.number.precision(.fractionLength(3)))) \(suffix)")
        .font(.callout.monospacedDigit())
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(10)
    .background(
      Color.primary.opacity(0.04),
      in: RoundedRectangle(cornerRadius: 10, style: .continuous))
  }

  private func booleanMetric(_ label: String, _ value: Bool) -> some View {
    VStack(alignment: .leading, spacing: 3) {
      Text(label.uppercased())
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      Label(value ? "Yes" : "No", systemImage: value ? "checkmark.circle.fill" : "circle")
        .font(.callout)
        .foregroundStyle(value ? Color.green : Color.secondary)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(10)
    .background(
      Color.primary.opacity(0.04),
      in: RoundedRectangle(cornerRadius: 10, style: .continuous))
  }

  private func errorCard(_ message: String) -> some View {
    IntelligenceCard {
      Label(message, systemImage: "exclamationmark.triangle.fill")
        .foregroundStyle(.red)
    }
  }
}
