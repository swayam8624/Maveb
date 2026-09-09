import AppKit
import Foundation
import SwiftUI

private struct WorldHistoryEnvelope: Decodable {
  let schemaVersion: Int
  let snapshots: [WorldRevisionSummary]
  let nextEntityId: UInt64
}

private struct WorldRevisionSummary: Decodable, Identifiable, Equatable {
  let revision: UInt64
  let timestamp: UInt64
  let entityCount: Int
  var id: UInt64 { revision }

  var date: Date {
    Date(timeIntervalSince1970: Double(timestamp) / 1_000_000_000.0)
  }
}

private struct RealityDiffSummary: Decodable, Equatable {
  let added: Int
  let removed: Int
  let modified: Int
  let unchanged: Int
  let changeRatio: Double
}

private struct RealityEntityDelta: Decodable, Identifiable, Equatable {
  let id: UInt64
  let name: String
  let flags: [String]
  let translationMeters: Double
  let rotationRadians: Double
  let relativeScale: Double
  let boundsMeters: Double
  let confidenceDelta: Double
}

private struct RealityDiffEnvelope: Decodable, Equatable {
  let schemaVersion: Int
  let available: Bool
  let beforeRevision: UInt64?
  let afterRevision: UInt64?
  let beforeTimestamp: UInt64?
  let afterTimestamp: UInt64?
  let summary: RealityDiffSummary?
  let entities: [RealityEntityDelta]?
  let truncated: Bool?
  let totalEntityDeltas: Int?
  let error: String?
}

private struct WorldIngestReport: Decodable, Equatable {
  let schemaVersion: Int
  let revision: UInt64
  let reusedIds: Int
  let createdIds: Int
  let missingPreviousEntities: Int
  let dirtyRegionCount: Int
  let summary: RealityDiffSummary
  let historyCount: Int
}

private final class SendableWorldBridge: @unchecked Sendable {
  let value = AetherWorldBridge()
}

@MainActor
private final class WorldHistoryModel: ObservableObject {
  @Published var revisions: [WorldRevisionSummary] = []
  @Published var diff: RealityDiffEnvelope?
  @Published var latestIngest: WorldIngestReport?
  @Published var isBusy = false
  @Published var status = "No persistent world loaded"
  @Published var errorMessage: String?

  private let native = SendableWorldBridge()
  private var lastTimestamp: UInt64 = 0

  var hasWorld: Bool { !revisions.isEmpty }

  func loadArchive(_ url: URL) {
    guard !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Loading persistent world…"
    let native = native
    Task {
      do {
        let payload = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard AetherWorldLoadArchive(native.value, url, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadUnknown)
          }
          return try Self.readState(from: native.value)
        }.value
        apply(payload)
        status = "Loaded \(revisions.count) world revision\(revisions.count == 1 ? "" : "s")"
      } catch {
        errorMessage = error.localizedDescription
        status = "World archive load failed"
      }
      isBusy = false
    }
  }

  func saveArchive(_ url: URL) {
    guard !isBusy, hasWorld else { return }
    isBusy = true
    errorMessage = nil
    status = "Saving persistent world…"
    let native = native
    Task {
      do {
        try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard AetherWorldSaveArchive(native.value, url, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileWriteUnknown)
          }
        }.value
        status = "Saved \(revisions.count) persistent world revision\(revisions.count == 1 ? "" : "s")"
      } catch {
        errorMessage = error.localizedDescription
        status = "World archive save failed"
      }
      isBusy = false
    }
  }

  func ingestCanonical(_ directory: URL, autoSaveURL: URL?) {
    guard !isBusy else { return }
    isBusy = true
    errorMessage = nil
    status = "Associating canonical reconstruction with persistent reality…"
    let timestamp = nextTimestamp()
    let native = native
    Task {
      do {
        let result = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let transactionData = AetherWorldIngestCanonical(
            native.value, directory, timestamp, &bridgeError)
          else {
            throw bridgeError ?? CocoaError(.fileReadCorruptFile)
          }
          if let autoSaveURL {
            bridgeError = nil
            guard AetherWorldSaveArchive(native.value, autoSaveURL, &bridgeError) else {
              throw bridgeError ?? CocoaError(.fileWriteUnknown)
            }
          }
          let state = try Self.readState(from: native.value)
          let transaction = try JSONDecoder().decode(WorldIngestReport.self, from: transactionData)
          return (state, transaction)
        }.value
        apply(result.0)
        latestIngest = result.1
        status = autoSaveURL == nil
          ? "Committed revision \(result.1.revision) • unsaved"
          : "Committed and saved revision \(result.1.revision)"
      } catch {
        errorMessage = error.localizedDescription
        status = "Canonical world ingest failed"
      }
      isBusy = false
    }
  }

  func refresh() {
    guard !isBusy else { return }
    isBusy = true
    errorMessage = nil
    let native = native
    Task {
      do {
        let payload = try await Task.detached(priority: .utility) {
          try Self.readState(from: native.value)
        }.value
        apply(payload)
        status = "Persistent world refreshed"
      } catch {
        errorMessage = error.localizedDescription
        status = "Persistent world refresh failed"
      }
      isBusy = false
    }
  }

  private func nextTimestamp() -> UInt64 {
    let wallClock = UInt64(max(0, Date().timeIntervalSince1970) * 1_000_000_000.0)
    let sequenceFloor = lastTimestamp == UInt64.max ? UInt64.max : lastTimestamp + 1
    let next = max(wallClock, sequenceFloor)
    lastTimestamp = next
    return next
  }

  private func apply(_ payload: (WorldHistoryEnvelope, RealityDiffEnvelope)) {
    revisions = payload.0.snapshots
    diff = payload.1
    if let newest = revisions.last {
      lastTimestamp = max(lastTimestamp, newest.timestamp)
    }
  }

  nonisolated private static func readState(
    from bridge: AetherWorldBridge
  ) throws -> (WorldHistoryEnvelope, RealityDiffEnvelope) {
    var bridgeError: NSError?
    guard let historyData = AetherWorldHistoryJSON(bridge, &bridgeError) else {
      throw bridgeError ?? CocoaError(.fileReadCorruptFile)
    }
    bridgeError = nil
    guard let diffData = AetherWorldLatestDiffJSON(bridge, &bridgeError) else {
      throw bridgeError ?? CocoaError(.fileReadCorruptFile)
    }
    let decoder = JSONDecoder()
    return (
      try decoder.decode(WorldHistoryEnvelope.self, from: historyData),
      try decoder.decode(RealityDiffEnvelope.self, from: diffData)
    )
  }
}

private struct WorldHistoryCard<Content: View>: View {
  let content: Content
  init(@ViewBuilder content: () -> Content) { self.content = content() }

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

private struct WorldMetric: View {
  let label: String
  let value: String
  let symbol: String

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      Label(label.uppercased(), systemImage: symbol)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
        .tracking(0.6)
      Text(value)
        .font(.headline.monospacedDigit())
        .lineLimit(1)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(12)
    .background(
      Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
  }
}

struct WorldHistoryWorkspace: View {
  @Binding var archivePath: String?
  @StateObject private var model = WorldHistoryModel()
  @State private var restoredProjectArchive = false

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        hero
        controls
        if let errorMessage = model.errorMessage { errorCard(errorMessage) }
        if let ingest = model.latestIngest { ingestCard(ingest) }
        if model.hasWorld { timelineCard }
        diffCard
      }
      .padding(28)
      .frame(maxWidth: 1180, alignment: .leading)
    }
    .background(Color(nsColor: .windowBackgroundColor))
    .onAppear {
      guard !restoredProjectArchive else { return }
      restoredProjectArchive = true
      if let archivePath {
        model.loadArchive(URL(fileURLWithPath: archivePath))
      }
    }
    .onChange(of: archivePath) { _, newPath in
      guard restoredProjectArchive, let newPath else { return }
      if model.revisions.isEmpty {
        model.loadArchive(URL(fileURLWithPath: newPath))
      }
    }
  }

  private var hero: some View {
    HStack(alignment: .center, spacing: 18) {
      ZStack {
        RoundedRectangle(cornerRadius: 18, style: .continuous)
          .fill(Color.accentColor.opacity(0.11))
        Image(systemName: "clock.arrow.trianglehead.counterclockwise.rotate.90")
          .font(.system(size: 30, weight: .light))
          .foregroundStyle(Color.accentColor)
      }
      .frame(width: 76, height: 76)

      VStack(alignment: .leading, spacing: 5) {
        Text("Persistent Reality")
          .font(.title2.weight(.semibold))
        Text(
          "Ingest validated canonical reconstructions as revisions of one world. Stable identity, Reality Diff, and local dirty regions are computed by the native engine."
        )
        .font(.callout)
        .foregroundStyle(.secondary)
        .frame(maxWidth: 720, alignment: .leading)
        Label(model.status, systemImage: model.hasWorld ? "checkmark.seal.fill" : "circle.dashed")
          .font(.caption.weight(.medium))
          .foregroundStyle(model.hasWorld ? Color.green : Color.secondary)
      }
      Spacer()
      if model.isBusy { ProgressView().controlSize(.small) }
    }
  }

  private var controls: some View {
    WorldHistoryCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionHeader("World memory", symbol: "externaldrive.badge.timemachine")
        HStack(spacing: 10) {
          Button("Open World…", systemImage: "folder", action: openArchive)
            .disabled(model.isBusy)
          Button("Ingest Canonical…", systemImage: "camera.metering.matrix", action: ingestCanonical)
            .buttonStyle(.borderedProminent)
            .disabled(model.isBusy)
          Button("Save World As…", systemImage: "square.and.arrow.down", action: saveArchive)
            .disabled(model.isBusy || !model.hasWorld)
          Button("Refresh", systemImage: "arrow.clockwise", action: model.refresh)
            .disabled(model.isBusy || !model.hasWorld)
          Spacer()
        }

        HStack(spacing: 9) {
          Image(systemName: archivePath == nil ? "exclamationmark.circle" : "link")
            .foregroundStyle(.secondary)
          Text(
            archivePath
              ?? "No archive linked to this project yet. Ingested history remains in memory until saved."
          )
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(2)
          .truncationMode(.middle)
          Spacer()
        }
      }
    }
  }

  private var timelineCard: some View {
    WorldHistoryCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionHeader("Revision timeline", symbol: "point.3.connected.trianglepath.dotted")
        HStack(spacing: 10) {
          WorldMetric(label: "Revisions", value: "\(model.revisions.count)", symbol: "clock")
          WorldMetric(
            label: "Latest entities", value: "\(model.revisions.last?.entityCount ?? 0)",
            symbol: "cube.transparent")
          WorldMetric(
            label: "Latest revision", value: "r\(model.revisions.last?.revision ?? 0)",
            symbol: "number")
        }

        LazyVStack(spacing: 8) {
          ForEach(Array(model.revisions.reversed())) { revision in
            HStack(spacing: 12) {
              ZStack {
                Circle().fill(Color.accentColor.opacity(0.13))
                Text("\(revision.revision)")
                  .font(.caption2.monospacedDigit().weight(.semibold))
              }
              .frame(width: 34, height: 34)
              VStack(alignment: .leading, spacing: 2) {
                Text("Revision \(revision.revision)")
                  .font(.callout.weight(.medium))
                Text(revision.date.formatted(date: .abbreviated, time: .standard))
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
              Spacer()
              Label("\(revision.entityCount) entities", systemImage: "cube")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            .padding(.vertical, 4)
            if revision.id != model.revisions.first?.id { Divider().opacity(0.45) }
          }
        }
      }
    }
  }

  private var diffCard: some View {
    WorldHistoryCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionHeader("Reality Diff", symbol: "arrow.left.arrow.right")
        if let diff = model.diff, diff.available, let summary = diff.summary {
          HStack(spacing: 10) {
            WorldMetric(label: "Added", value: "\(summary.added)", symbol: "plus.circle")
            WorldMetric(label: "Removed", value: "\(summary.removed)", symbol: "minus.circle")
            WorldMetric(label: "Modified", value: "\(summary.modified)", symbol: "pencil.circle")
            WorldMetric(
              label: "Changed",
              value: summary.changeRatio.formatted(.percent.precision(.fractionLength(1))),
              symbol: "percent")
          }

          HStack {
            Text("r\(diff.beforeRevision ?? 0) → r\(diff.afterRevision ?? 0)")
              .font(.caption.monospacedDigit().weight(.semibold))
            Spacer()
            if diff.truncated == true {
              Label(
                "Showing first \(diff.entities?.count ?? 0) of \(diff.totalEntityDeltas ?? 0)",
                systemImage: "ellipsis.circle")
                .font(.caption)
                .foregroundStyle(.secondary)
            }
          }

          if let entities = diff.entities, !entities.isEmpty {
            LazyVStack(spacing: 8) {
              ForEach(entities) { entity in deltaRow(entity) }
            }
          } else {
            Text("No entity-level changes exceeded the active Reality Diff thresholds.")
              .font(.callout)
              .foregroundStyle(.secondary)
          }
        } else {
          Text(model.diff?.error ?? "Capture or author a second revision to compare reality across time.")
            .font(.callout)
            .foregroundStyle(.secondary)
        }
      }
    }
  }

  private func deltaRow(_ entity: RealityEntityDelta) -> some View {
    HStack(alignment: .top, spacing: 12) {
      Image(systemName: deltaSymbol(entity.flags))
        .frame(width: 24, height: 24)
        .foregroundStyle(Color.accentColor)
      VStack(alignment: .leading, spacing: 5) {
        HStack {
          Text(entity.name.isEmpty ? "Entity #\(entity.id)" : entity.name)
            .font(.callout.weight(.medium))
          Text("#\(entity.id)")
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.tertiary)
        }
        FlowFlags(flags: entity.flags)
        if entity.translationMeters > 0 || entity.rotationRadians > 0 || entity.relativeScale > 0 {
          Text(
            "Δ position \(entity.translationMeters.formatted(.number.precision(.fractionLength(3)))) m  •  Δ rotation \(entity.rotationRadians.formatted(.number.precision(.fractionLength(3)))) rad  •  Δ scale \(entity.relativeScale.formatted(.percent.precision(.fractionLength(1))))"
          )
          .font(.caption2.monospacedDigit())
          .foregroundStyle(.secondary)
        }
      }
      Spacer()
    }
    .padding(10)
    .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 10))
  }

  private func ingestCard(_ report: WorldIngestReport) -> some View {
    WorldHistoryCard {
      VStack(alignment: .leading, spacing: 12) {
        sectionHeader("Last world transaction", symbol: "bolt.horizontal.circle")
        HStack(spacing: 10) {
          WorldMetric(label: "Revision", value: "r\(report.revision)", symbol: "number")
          WorldMetric(label: "Reused IDs", value: "\(report.reusedIds)", symbol: "link")
          WorldMetric(label: "New IDs", value: "\(report.createdIds)", symbol: "plus")
          WorldMetric(
            label: "Dirty regions", value: "\(report.dirtyRegionCount)", symbol: "square.grid.3x3")
        }
      }
    }
  }

  private func errorCard(_ message: String) -> some View {
    WorldHistoryCard {
      HStack(alignment: .top, spacing: 10) {
        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
        VStack(alignment: .leading, spacing: 3) {
          Text("Persistent-world operation failed").font(.callout.weight(.semibold))
          Text(message).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
        }
        Spacer()
      }
    }
  }

  private func sectionHeader(_ title: String, symbol: String) -> some View {
    Label(title.uppercased(), systemImage: symbol)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(.secondary)
      .tracking(0.7)
  }

  private func openArchive() {
    let panel = NSOpenPanel()
    panel.title = "Open Persistent World Archive"
    panel.canChooseFiles = true
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = false
    guard panel.runModal() == .OK, let url = panel.url else { return }
    archivePath = url.path
    model.loadArchive(url)
  }

  private func saveArchive() {
    let panel = NSSavePanel()
    panel.title = "Save Persistent World Archive"
    panel.nameFieldStringValue = "world-history.maveb-world.json"
    guard panel.runModal() == .OK, let url = panel.url else { return }
    archivePath = url.path
    model.saveArchive(url)
  }

  private func ingestCanonical() {
    let panel = NSOpenPanel()
    panel.title = "Choose Canonical Reconstruction Directory"
    panel.canChooseFiles = false
    panel.canChooseDirectories = true
    panel.allowsMultipleSelection = false
    guard panel.runModal() == .OK, let url = panel.url else { return }
    let saveURL = archivePath.map { URL(fileURLWithPath: $0) }
    model.ingestCanonical(url, autoSaveURL: saveURL)
  }

  private func deltaSymbol(_ flags: [String]) -> String {
    if flags.contains("added") { return "plus.circle.fill" }
    if flags.contains("removed") { return "minus.circle.fill" }
    if flags.contains("translated") || flags.contains("rotated") || flags.contains("scaled") {
      return "move.3d"
    }
    if flags.contains("geometry") { return "cube.transparent" }
    if flags.contains("appearance") { return "paintpalette" }
    if flags.contains("semantic") { return "tag" }
    return "pencil.circle"
  }
}

private struct FlowFlags: View {
  let flags: [String]

  var body: some View {
    HStack(spacing: 5) {
      ForEach(Array(flags.prefix(6)), id: \.self) { flag in
        Text(flag)
          .font(.caption2.weight(.medium))
          .padding(.horizontal, 7)
          .padding(.vertical, 3)
          .background(Color.accentColor.opacity(0.09), in: Capsule())
      }
      if flags.count > 6 {
        Text("+\(flags.count - 6)")
          .font(.caption2.monospacedDigit())
          .foregroundStyle(.secondary)
      }
    }
  }
}
