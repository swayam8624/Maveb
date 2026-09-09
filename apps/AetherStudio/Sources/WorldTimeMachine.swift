import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

private struct TimeMachineHistoryEnvelope: Decodable, Sendable {
  let schemaVersion: Int
  let snapshots: [TimeMachineRevision]
  let nextEntityId: UInt64
}

private struct TimeMachineRevision: Decodable, Identifiable, Equatable, Sendable {
  let revision: UInt64
  let timestamp: UInt64
  let entityCount: Int

  var id: UInt64 { revision }

  var date: Date {
    Date(timeIntervalSince1970: Double(timestamp) / 1_000_000_000.0)
  }
}

private struct TimeMachineDiffSummary: Decodable, Equatable, Sendable {
  let added: Int
  let removed: Int
  let modified: Int
  let unchanged: Int
  let changeRatio: Double
}

private struct TimeMachineRestoreReport: Decodable, Equatable, Sendable {
  let schemaVersion: Int
  let revision: UInt64
  let sourceRevision: UInt64
  let dirtyRegionCount: Int
  let summary: TimeMachineDiffSummary
}

private final class SendableTimeMachineBridge: @unchecked Sendable {
  let value = AetherWorldBridge()
}

@MainActor
private final class WorldTimeMachineModel: ObservableObject {
  @Published var archiveURL: URL?
  @Published var revisions: [TimeMachineRevision] = []
  @Published var selectedRevision: UInt64?
  @Published var lastRestore: TimeMachineRestoreReport?
  @Published var isBusy = false
  @Published var status = "Open a persistent-world archive to travel through its history."
  @Published var errorMessage: String?

  private let native = SendableTimeMachineBridge()
  private var lastTimestamp: UInt64 = 0

  var latestRevision: TimeMachineRevision? { revisions.last }

  var selected: TimeMachineRevision? {
    guard let selectedRevision else { return nil }
    return revisions.first(where: { $0.revision == selectedRevision })
  }

  var canRestore: Bool {
    guard let selectedRevision, let latestRevision else { return false }
    return selectedRevision != latestRevision.revision && !isBusy
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
    status = "Loading persistent world history…"
    let native = native

    Task {
      do {
        let history = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard AetherWorldLoadArchive(native.value, url, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadUnknown)
          }
          return try Self.readHistory(from: native.value)
        }.value
        archiveURL = url
        apply(history)
        status = "Loaded \(revisions.count) immutable world revision\(revisions.count == 1 ? "" : "s")"
      } catch {
        errorMessage = error.localizedDescription
        status = "World history load failed"
      }
      isBusy = false
    }
  }

  func select(_ revision: UInt64?) {
    selectedRevision = revision
  }

  func restoreSelected() {
    guard let sourceRevision = selectedRevision, let archiveURL, canRestore else { return }
    isBusy = true
    errorMessage = nil
    status = "Restoring revision \(sourceRevision) as a new present…"
    let timestamp = nextTimestamp()
    let native = native

    Task {
      do {
        let result = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let reportData = AetherWorldRevertToRevision(
            native.value, sourceRevision, timestamp, &bridgeError)
          else {
            throw bridgeError ?? CocoaError(.fileWriteUnknown)
          }

          bridgeError = nil
          guard AetherWorldSaveArchive(native.value, archiveURL, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileWriteUnknown)
          }

          let report = try JSONDecoder().decode(TimeMachineRestoreReport.self, from: reportData)
          let history = try Self.readHistory(from: native.value)
          return (report, history)
        }.value

        lastRestore = result.0
        apply(result.1, preferredSelection: result.0.sourceRevision)
        status =
          "Restored revision \(result.0.sourceRevision) as new revision \(result.0.revision) and saved it"
      } catch {
        errorMessage = error.localizedDescription
        status = "World restore failed"
      }
      isBusy = false
    }
  }

  func refresh() {
    guard archiveURL != nil, !isBusy else { return }
    isBusy = true
    errorMessage = nil
    let native = native

    Task {
      do {
        let history = try await Task.detached(priority: .utility) {
          try Self.readHistory(from: native.value)
        }.value
        apply(history, preferredSelection: selectedRevision)
        status = "World history refreshed"
      } catch {
        errorMessage = error.localizedDescription
        status = "World history refresh failed"
      }
      isBusy = false
    }
  }

  private func nextTimestamp() -> UInt64 {
    let wallClockSeconds = max(0, Date().timeIntervalSince1970)
    let wallClock = UInt64(wallClockSeconds * 1_000_000_000.0)
    let sequenceFloor = lastTimestamp == UInt64.max ? UInt64.max : lastTimestamp + 1
    let timestamp = max(wallClock, sequenceFloor)
    lastTimestamp = timestamp
    return timestamp
  }

  private func apply(
    _ history: TimeMachineHistoryEnvelope,
    preferredSelection: UInt64? = nil
  ) {
    revisions = history.snapshots
    if let latest = revisions.last {
      lastTimestamp = max(lastTimestamp, latest.timestamp)
    }

    if let preferredSelection,
      revisions.contains(where: { $0.revision == preferredSelection })
    {
      selectedRevision = preferredSelection
    } else if revisions.count >= 2 {
      selectedRevision = revisions[revisions.count - 2].revision
    } else {
      selectedRevision = revisions.first?.revision
    }
  }

  nonisolated private static func readHistory(
    from bridge: AetherWorldBridge
  ) throws -> TimeMachineHistoryEnvelope {
    var bridgeError: NSError?
    guard let data = AetherWorldHistoryJSON(bridge, &bridgeError) else {
      throw bridgeError ?? CocoaError(.fileReadCorruptFile)
    }
    return try JSONDecoder().decode(TimeMachineHistoryEnvelope.self, from: data)
  }
}

struct WorldTimeMachineWindow: View {
  @StateObject private var model = WorldTimeMachineModel()

  var body: some View {
    NavigationSplitView {
      timeline
    } detail: {
      detail
    }
    .navigationSplitViewStyle(.balanced)
    .frame(minWidth: 980, minHeight: 680)
    .toolbar {
      ToolbarItemGroup {
        Button("Open World…", systemImage: "folder", action: model.chooseArchive)
        Button("Refresh", systemImage: "arrow.clockwise", action: model.refresh)
          .disabled(model.archiveURL == nil || model.isBusy)
      }
    }
  }

  private var timeline: some View {
    VStack(spacing: 0) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text("REALITY TIMELINE")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .tracking(0.8)
          Text("\(model.revisions.count) revisions")
            .font(.caption.monospacedDigit())
            .foregroundStyle(.tertiary)
        }
        Spacer()
        if model.isBusy { ProgressView().controlSize(.small) }
      }
      .padding(14)

      Divider()

      if model.revisions.isEmpty {
        ContentUnavailableView(
          "No World History",
          systemImage: "clock.arrow.trianglehead.counterclockwise.rotate.90",
          description: Text("Open a persistent-world archive to inspect its revision history."))
      } else {
        List(selection: Binding(get: { model.selectedRevision }, set: model.select)) {
          ForEach(Array(model.revisions.reversed())) { revision in
            VStack(alignment: .leading, spacing: 4) {
              HStack {
                Text("Revision \(revision.revision)")
                  .font(.callout.weight(.medium))
                Spacer()
                if revision.revision == model.latestRevision?.revision {
                  Text("PRESENT")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.green)
                }
              }
              Text(revision.date.formatted(date: .abbreviated, time: .standard))
                .font(.caption)
                .foregroundStyle(.secondary)
              Label("\(revision.entityCount) entities", systemImage: "cube")
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.tertiary)
            }
            .padding(.vertical, 4)
            .tag(revision.revision)
          }
        }
        .listStyle(.sidebar)
      }
    }
    .navigationSplitViewColumnWidth(min: 280, ideal: 330, max: 420)
  }

  private var detail: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        hero
        if let errorMessage = model.errorMessage { errorCard(errorMessage) }
        if let selected = model.selected { restoreCard(selected) }
        if let report = model.lastRestore { restoreReportCard(report) }
        invariantsCard
      }
      .padding(28)
      .frame(maxWidth: 900, alignment: .leading)
    }
    .background(Color(nsColor: .windowBackgroundColor))
  }

  private var hero: some View {
    HStack(spacing: 16) {
      ZStack {
        RoundedRectangle(cornerRadius: 16, style: .continuous)
          .fill(Color.accentColor.opacity(0.12))
        Image(systemName: "clock.arrow.trianglehead.counterclockwise.rotate.90")
          .font(.system(size: 28, weight: .light))
          .foregroundStyle(Color.accentColor)
      }
      .frame(width: 70, height: 70)

      VStack(alignment: .leading, spacing: 5) {
        Text("Reality Time Machine")
          .font(.title2.weight(.semibold))
        Text(model.status)
          .font(.callout)
          .foregroundStyle(.secondary)
        if let archiveURL = model.archiveURL {
          Text(archiveURL.path)
            .font(.caption)
            .foregroundStyle(.tertiary)
            .lineLimit(1)
            .truncationMode(.middle)
        }
      }
      Spacer()
    }
  }

  private func restoreCard(_ revision: TimeMachineRevision) -> some View {
    timeCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionTitle("Selected historical state", symbol: "clock")
        HStack(spacing: 12) {
          metric("Revision", "r\(revision.revision)", symbol: "number")
          metric("Entities", "\(revision.entityCount)", symbol: "cube")
          metric(
            "Observed",
            revision.date.formatted(date: .numeric, time: .shortened),
            symbol: "calendar")
        }

        Divider()

        if revision.revision == model.latestRevision?.revision {
          Label(
            "This revision is already the present. Choose an earlier revision to travel back.",
            systemImage: "checkmark.circle.fill")
            .font(.callout)
            .foregroundStyle(.secondary)
        } else {
          Text(
            "Restoring does not delete newer revisions. Maveb copies this historical state into a new revision, computes Reality Diff against the current present, schedules only affected spatial regions, and preserves the stable-ID allocator."
          )
          .font(.callout)
          .foregroundStyle(.secondary)

          HStack {
            Spacer()
            Button(
              "Restore as New Revision", systemImage: "arrow.uturn.backward.circle.fill",
              action: model.restoreSelected)
              .buttonStyle(.borderedProminent)
              .controlSize(.large)
              .disabled(!model.canRestore)
          }
        }
      }
    }
  }

  private func restoreReportCard(_ report: TimeMachineRestoreReport) -> some View {
    timeCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionTitle("Last time-travel transaction", symbol: "arrow.triangle.branch")
        HStack(spacing: 12) {
          metric("Source", "r\(report.sourceRevision)", symbol: "clock.arrow.circlepath")
          metric("New present", "r\(report.revision)", symbol: "sparkles")
          metric("Dirty regions", "\(report.dirtyRegionCount)", symbol: "square.grid.3x3")
        }
        HStack(spacing: 10) {
          changePill("Added \(report.summary.added)", symbol: "plus.circle")
          changePill("Removed \(report.summary.removed)", symbol: "minus.circle")
          changePill("Modified \(report.summary.modified)", symbol: "pencil.circle")
          changePill(
            report.summary.changeRatio.formatted(.percent.precision(.fractionLength(1))),
            symbol: "percent")
        }
      }
    }
  }

  private var invariantsCard: some View {
    timeCard {
      VStack(alignment: .leading, spacing: 12) {
        sectionTitle("Time-travel invariants", symbol: "checkmark.shield")
        invariant(
          "Append-only history",
          "Going back creates a new present; no committed revision is overwritten or erased.")
        invariant(
          "Identity never rewinds",
          "Stable entity IDs allocated in later revisions remain retired even after restoring an older state.")
        invariant(
          "Local reconstruction",
          "The reversal is diffed against the current present and only affected metric regions are dirtied.")
      }
    }
  }

  private func invariant(_ title: String, _ description: String) -> some View {
    HStack(alignment: .top, spacing: 10) {
      Image(systemName: "checkmark.circle.fill")
        .foregroundStyle(.green)
      VStack(alignment: .leading, spacing: 2) {
        Text(title).font(.callout.weight(.medium))
        Text(description).font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private func errorCard(_ message: String) -> some View {
    timeCard {
      Label(message, systemImage: "exclamationmark.triangle.fill")
        .foregroundStyle(.red)
    }
  }

  private func sectionTitle(_ title: String, symbol: String) -> some View {
    Label(title.uppercased(), systemImage: symbol)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(.secondary)
      .tracking(0.7)
  }

  private func metric(_ label: String, _ value: String, symbol: String) -> some View {
    VStack(alignment: .leading, spacing: 5) {
      Label(label.uppercased(), systemImage: symbol)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      Text(value)
        .font(.headline.monospacedDigit())
        .lineLimit(1)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(12)
    .background(
      Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
  }

  private func changePill(_ text: String, symbol: String) -> some View {
    Label(text, systemImage: symbol)
      .font(.caption.weight(.medium))
      .padding(.horizontal, 9)
      .padding(.vertical, 6)
      .background(Color.primary.opacity(0.055), in: Capsule())
  }

  private func timeCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
    content()
      .padding(18)
      .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 16, style: .continuous)
          .stroke(Color.primary.opacity(0.08), lineWidth: 1)
      }
  }
}
