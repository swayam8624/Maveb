import AppKit
import Foundation
import SwiftUI

private struct CaptureReport: Decodable {
  struct Summary: Decodable {
    let imageCount: Int
    let sourceBytes: UInt64
    let estimatedWorkingBytes: UInt64
    let medianSharpness: Double
    let exposureSpreadStops: Double
  }

  struct Issue: Decodable, Identifiable {
    var id: String { "\(code):\(path ?? message)" }
    let severity: String
    let code: String
    let message: String
    let path: String?
  }

  let valid: Bool
  let root: String
  let summary: Summary
  let issues: [Issue]
}

@MainActor
private final class ReconstructionModel: ObservableObject {
  enum State: Equatable {
    case idle, validating, ready, running, complete
    case failed(String)
    case cancelled
  }

  @Published var datasetURL: URL?
  @Published var outputURL: URL?
  @Published var colmapURL: URL?
  @Published var brushURL: URL?
  @Published var proxyURL: URL?
  @Published var report: CaptureReport?
  @Published var coverageReport: SparseCoverageReport?
  @Published var checkpoints: [TrainingCheckpoint] = []
  @Published var state: State = .idle
  @Published var transcript = ""
  @Published var completedStages = 0
  private var process: Process?

  func chooseDataset() {
    guard let url = chooseDirectory(title: "Choose Capture Dataset") else { return }
    datasetURL = url
    outputURL = url.deletingLastPathComponent().appendingPathComponent(
      "\(url.lastPathComponent)-aether-job")
    report = nil
    coverageReport = nil
    checkpoints = []
    state = .idle
  }

  func chooseOutput() {
    guard let url = chooseDirectory(title: "Choose Reconstruction Job Directory") else { return }
    outputURL = url
    coverageReport = nil
    checkpoints = []
    Task {
      coverageReport = await readCoverageReport(from: url)
      checkpoints = await readCheckpoints(from: url)
    }
  }

  func chooseCOLMAP() { colmapURL = chooseExecutable(title: "Choose COLMAP 3.13.0") }
  func chooseBrush() { brushURL = chooseExecutable(title: "Choose Brush 0.3.0") }
  func chooseProxy() { proxyURL = chooseExecutable(title: "Choose AETHER Proxy Tool") }

  func validate() {
    guard let datasetURL else { return }
    state = .validating
    report = nil
    Task {
      do {
        let data = try await Task.detached(priority: .userInitiated) {
          var bridgeError: NSError?
          guard let data = AetherValidateCaptureDirectory(datasetURL, &bridgeError) else {
            throw bridgeError ?? CocoaError(.fileReadUnknown)
          }
          return data
        }.value
        let decoded = try JSONDecoder().decode(CaptureReport.self, from: data)
        report = decoded
        state = decoded.valid ? .ready : .failed("Capture validation found blocking errors.")
      } catch {
        state = .failed(error.localizedDescription)
      }
    }
  }

  func reconstruct() {
    guard case .ready = state, let datasetURL, let outputURL, let colmapURL, let brushURL,
      let proxyURL
    else { return }
    guard let helper = Bundle.main.url(forAuxiliaryExecutable: "aether-reconstruct") else {
      state = .failed("The signed reconstruction helper is missing from the app bundle.")
      return
    }

    let task = Process()
    let output = Pipe()
    task.executableURL = helper
    task.arguments = [
      datasetURL.path, "--output", outputURL.path, "--trainer", "brush",
      "--colmap", colmapURL.path, "--brush", brushURL.path,
      "--proxy", proxyURL.path, "--json",
    ]
    task.standardOutput = output
    task.standardError = output
    process = task
    transcript = ""
    coverageReport = nil
    checkpoints = []
    completedStages = 0
    state = .running

    Task {
      do {
        try task.run()
        Task { await monitorMarkers(in: outputURL, process: task) }
        let data = await Task.detached { output.fileHandleForReading.readDataToEndOfFile() }.value
        task.waitUntilExit()
        transcript = String(decoding: data, as: UTF8.self)
        coverageReport = await readCoverageReport(from: outputURL)
        checkpoints = await readCheckpoints(from: outputURL)
        process = nil

        if task.terminationReason == .uncaughtSignal || task.terminationStatus == 130 {
          state = .cancelled
        } else if task.terminationStatus == 0 {
          state = .complete
        } else if coverageReport?.passed == false {
          state = .failed("Sparse pose coverage is not sufficient for training.")
        } else {
          state = .failed(
            "Reconstruction exited with code \(task.terminationStatus). See the job logs.")
        }
      } catch {
        process = nil
        state = .failed(error.localizedDescription)
      }
    }
  }

  func cancel() { process?.interrupt() }

  private func readCoverageReport(from outputURL: URL) async -> SparseCoverageReport? {
    let reportURL = outputURL.appendingPathComponent("pose-coverage.json")
    return await Task.detached(priority: .utility) {
      guard let data = try? Data(contentsOf: reportURL) else { return nil }
      return try? JSONDecoder().decode(SparseCoverageReport.self, from: data)
    }.value
  }

  private func readCheckpoints(from outputURL: URL) async -> [TrainingCheckpoint] {
    await Task.detached(priority: .utility) {
      (try? TrainingCheckpoint.discover(in: outputURL)) ?? []
    }.value
  }

  private func monitorMarkers(in outputURL: URL, process: Process) async {
    let stages = [
      "feature-extraction", "feature-matching", "sparse-mapping",
      "sparse-model-export", "pose-coverage-validation", "proxy-generation", "undistortion",
      "brush-training",
    ]
    while process.isRunning {
      completedStages =
        stages.filter {
          FileManager.default.fileExists(
            atPath: outputURL.appendingPathComponent("\($0).complete").path)
        }.count
      try? await Task.sleep(for: .milliseconds(500))
    }
    completedStages =
      stages.filter {
        FileManager.default.fileExists(
          atPath: outputURL.appendingPathComponent("\($0).complete").path)
      }.count
  }

  private func chooseDirectory(title: String) -> URL? {
    let panel = NSOpenPanel()
    panel.title = title
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.canCreateDirectories = true
    return panel.runModal() == .OK ? panel.url : nil
  }

  private func chooseExecutable(title: String) -> URL? {
    let panel = NSOpenPanel()
    panel.title = title
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    return panel.runModal() == .OK ? panel.url : nil
  }
}

private struct ReconstructionCard<Content: View>: View {
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

private struct MetricTile: View {
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

struct ReconstructionWorkspace: View {
  @StateObject private var model = ReconstructionModel()
  @State private var leftCheckpoint: Int?
  @State private var rightCheckpoint: Int?
  @State private var comparisonCamera = AetherCameraState()

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        hero
        inputsCard
        runCard

        if let report = model.report { reportView(report) }
        if let coverage = model.coverageReport { coverageView(coverage) }
        if !model.checkpoints.isEmpty { checkpointComparison }
        if !model.transcript.isEmpty { processResult }
      }
      .padding(28)
      .frame(maxWidth: 1040, alignment: .leading)
    }
    .background(Color(nsColor: .windowBackgroundColor))
    .onChange(of: model.checkpoints) { _, checkpoints in
      guard !checkpoints.isEmpty else {
        leftCheckpoint = nil
        rightCheckpoint = nil
        return
      }
      if !checkpoints.contains(where: { $0.iteration == leftCheckpoint }) {
        leftCheckpoint = checkpoints.first?.iteration
      }
      if !checkpoints.contains(where: { $0.iteration == rightCheckpoint }) {
        rightCheckpoint = checkpoints.last?.iteration
      }
    }
  }

  private var hero: some View {
    HStack(alignment: .center, spacing: 18) {
      ZStack {
        RoundedRectangle(cornerRadius: 18, style: .continuous)
          .fill(Color.accentColor.opacity(0.11))
        Image(systemName: "camera.metering.matrix")
          .font(.system(size: 30, weight: .light))
          .foregroundStyle(Color.accentColor)
      }
      .frame(width: 76, height: 76)

      VStack(alignment: .leading, spacing: 5) {
        Text("Local Reconstruction")
          .font(.title2.weight(.semibold))
        Text(
          "Validate real image content, then run pinned COLMAP and Brush as isolated, resumable local processes."
        )
        .font(.callout)
        .foregroundStyle(.secondary)
        .frame(maxWidth: 650, alignment: .leading)
        Label("Capture data stays on this Mac", systemImage: "lock.fill")
          .font(.caption.weight(.medium))
          .foregroundStyle(.green)
      }

      Spacer()
      stateBadge
    }
  }

  private var inputsCard: some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionHeader("Inputs & tools", symbol: "folder.badge.gearshape")
        pickerRow(
          "Dataset", symbol: "photo.stack", value: model.datasetURL?.path,
          action: model.chooseDataset)
        Divider()
        pickerRow(
          "Job output", symbol: "externaldrive", value: model.outputURL?.path,
          action: model.chooseOutput)
        Divider()
        pickerRow(
          "COLMAP 3.13.0", symbol: "point.3.connected.trianglepath.dotted",
          value: model.colmapURL?.path, action: model.chooseCOLMAP)
        pickerRow(
          "Brush 0.3.0", symbol: "paintbrush", value: model.brushURL?.path,
          action: model.chooseBrush)
        pickerRow(
          "AETHER Proxy 0.1", symbol: "cube.transparent", value: model.proxyURL?.path,
          action: model.chooseProxy)
      }
    }
  }

  private var runCard: some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 14) {
        sectionHeader("Pipeline", symbol: "arrow.triangle.branch")

        if model.state == .running {
          VStack(alignment: .leading, spacing: 8) {
            HStack {
              Text("Reconstruction in progress")
                .font(.callout.weight(.medium))
              Spacer()
              Text("\(model.completedStages)/8 stages")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            ProgressView(value: Double(model.completedStages), total: 8)
              .progressViewStyle(.linear)
          }
        } else {
          Text(
            "Validate the capture before starting. A valid report unlocks the resumable reconstruction path."
          )
          .font(.callout)
          .foregroundStyle(.secondary)
        }

        HStack(spacing: 10) {
          Button("Validate Capture", systemImage: "checkmark.shield", action: model.validate)
            .disabled(
              model.datasetURL == nil || model.state == .validating || model.state == .running)

          Button("Start / Resume", systemImage: "play.fill", action: model.reconstruct)
            .buttonStyle(.borderedProminent)
            .disabled(
              model.state != .ready || model.outputURL == nil || model.colmapURL == nil
                || model.brushURL == nil || model.proxyURL == nil)

          if model.state == .running {
            Button("Cancel", systemImage: "stop.fill", role: .destructive, action: model.cancel)
          }

          Spacer()
        }
      }
    }
  }

  private func pickerRow(
    _ label: String, symbol: String, value: String?, action: @escaping () -> Void
  ) -> some View {
    HStack(spacing: 12) {
      ZStack {
        RoundedRectangle(cornerRadius: 9, style: .continuous)
          .fill(Color.primary.opacity(0.055))
        Image(systemName: symbol)
          .foregroundStyle(.secondary)
      }
      .frame(width: 34, height: 34)

      VStack(alignment: .leading, spacing: 2) {
        Text(label)
          .font(.callout.weight(.medium))
        Text(value ?? "Not selected")
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(1)
          .truncationMode(.middle)
      }

      Spacer(minLength: 12)
      Button("Choose…", action: action)
    }
  }

  private var stateBadge: some View {
    Group {
      switch model.state {
      case .idle:
        statusPill("Not validated", symbol: "circle.dashed", color: .gray)
      case .validating:
        HStack(spacing: 7) {
          ProgressView().controlSize(.small)
          Text("Validating")
        }
        .font(.caption.weight(.medium))
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(.thinMaterial, in: Capsule())
      case .ready:
        statusPill("Ready", symbol: "checkmark.circle.fill", color: .green)
      case .running:
        statusPill("Running", symbol: "gearshape.2.fill", color: .blue)
      case .complete:
        statusPill("Complete", symbol: "checkmark.seal.fill", color: .green)
      case .cancelled:
        statusPill("Cancelled", symbol: "stop.circle", color: .gray)
      case .failed:
        statusPill("Needs attention", symbol: "exclamationmark.triangle.fill", color: .red)
      }
    }
  }

  private func statusPill(_ text: String, symbol: String, color: Color) -> some View {
    Label(text, systemImage: symbol)
      .font(.caption.weight(.medium))
      .foregroundStyle(color)
      .padding(.horizontal, 10)
      .padding(.vertical, 7)
      .background(color.opacity(0.10), in: Capsule())
      .overlay { Capsule().stroke(color.opacity(0.18), lineWidth: 1) }
  }

  private func sectionHeader(_ title: String, symbol: String) -> some View {
    Label(title.uppercased(), systemImage: symbol)
      .font(.caption.weight(.semibold))
      .foregroundStyle(.secondary)
      .tracking(0.7)
  }

  private func reportView(_ report: CaptureReport) -> some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 14) {
        HStack {
          sectionHeader("Capture report", symbol: "checklist")
          Spacer()
          statusPill(
            report.valid ? "Valid" : "Blocked",
            symbol: report.valid ? "checkmark.circle.fill" : "xmark.octagon.fill",
            color: report.valid ? .green : .red)
        }

        HStack(spacing: 10) {
          MetricTile(label: "Images", value: "\(report.summary.imageCount)", symbol: "photo.stack")
          MetricTile(
            label: "Source",
            value: ByteCountFormatter.string(
              fromByteCount: Int64(report.summary.sourceBytes), countStyle: .file),
            symbol: "internaldrive")
          MetricTile(
            label: "Working",
            value: ByteCountFormatter.string(
              fromByteCount: Int64(report.summary.estimatedWorkingBytes), countStyle: .memory),
            symbol: "memorychip")
          MetricTile(
            label: "Exposure",
            value: String(format: "%.2f EV", report.summary.exposureSpreadStops),
            symbol: "sun.max")
        }

        if report.issues.isEmpty {
          Label("No blocking errors or quality warnings", systemImage: "checkmark.circle")
            .font(.callout)
            .foregroundStyle(.green)
        } else {
          VStack(alignment: .leading, spacing: 7) {
            ForEach(report.issues) { issue in
              Label(
                issue.message,
                systemImage: issue.severity == "error"
                  ? "xmark.octagon.fill"
                  : "exclamationmark.triangle.fill"
              )
              .font(.callout)
              .foregroundStyle(issue.severity == "error" ? .red : .orange)
            }
          }
        }
      }
    }
  }

  private func coverageView(_ report: SparseCoverageReport) -> some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 14) {
        HStack {
          sectionHeader(
            "Sparse pose coverage", symbol: "point.3.filled.connected.trianglepath.dotted")
          Spacer()
          statusPill(
            report.passed ? "Passed" : "Blocked",
            symbol: report.passed ? "checkmark.circle.fill" : "xmark.octagon.fill",
            color: report.passed ? .green : .red)
        }

        HStack(spacing: 10) {
          MetricTile(
            label: "Registered",
            value: "\(report.registeredImages)/\(report.inputImages)",
            symbol: "camera.on.rectangle")
          MetricTile(
            label: "Registration",
            value: report.registrationRatio.formatted(.percent.precision(.fractionLength(1))),
            symbol: "percent")
          MetricTile(
            label: "Tracked Points",
            value: report.trackedPoints.formatted(), symbol: "circle.grid.cross")
          MetricTile(
            label: "Mean Track",
            value: report.meanTrackLength.formatted(.number.precision(.fractionLength(1))),
            symbol: "point.topleft.down.to.point.bottomright.curvepath")
        }

        HStack(spacing: 10) {
          MetricTile(
            label: "Connected",
            value: "\(report.connectedImages)/\(report.registeredImages)",
            symbol: "link")
          MetricTile(
            label: "Graph Coverage",
            value: report.connectedImageRatio.formatted(.percent.precision(.fractionLength(1))),
            symbol: "network")
          MetricTile(
            label: "Baseline",
            value: report.baselineDiagonal.formatted(.number.precision(.significantDigits(4))),
            symbol: "ruler")
          MetricTile(
            label: "View Diversity",
            value: report.maximumViewAngleDegrees.formatted(.number.precision(.fractionLength(1)))
              + "°",
            symbol: "view.3d")
        }

        if !report.issues.isEmpty {
          VStack(alignment: .leading, spacing: 7) {
            ForEach(report.issues, id: \.self) { issue in
              Label(issue, systemImage: "xmark.octagon.fill")
                .font(.callout)
                .foregroundStyle(.red)
            }
          }
        }
      }
    }
  }

  private var checkpointComparison: some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 14) {
        HStack {
          sectionHeader("Training comparison", symbol: "rectangle.split.2x1")
          Spacer()
          Text("Synchronized camera")
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        HStack(spacing: 10) {
          checkpointPicker("Left", selection: $leftCheckpoint)
          checkpointPicker("Right", selection: $rightCheckpoint)
          Spacer()
        }

        if let left = checkpoint(leftCheckpoint), let right = checkpoint(rightCheckpoint) {
          HStack(spacing: 12) {
            comparisonPanel(left)
            comparisonPanel(right)
          }
          .frame(height: 380)
        }
      }
    }
  }

  private func checkpointPicker(_ label: String, selection: Binding<Int?>) -> some View {
    Picker(label, selection: selection) {
      ForEach(model.checkpoints) { checkpoint in
        Text("Step \(checkpoint.iteration.formatted())")
          .tag(Int?.some(checkpoint.iteration))
      }
    }
    .frame(width: 220)
  }

  private func checkpoint(_ iteration: Int?) -> TrainingCheckpoint? {
    model.checkpoints.first { $0.iteration == iteration }
  }

  private func comparisonPanel(_ checkpoint: TrainingCheckpoint) -> some View {
    VStack(spacing: 7) {
      HStack {
        Text("Step \(checkpoint.iteration.formatted())")
          .font(.caption.weight(.semibold))
        Spacer()
        Text(ByteCountFormatter.string(fromByteCount: Int64(checkpoint.bytes), countStyle: .file))
          .font(.caption2)
          .foregroundStyle(.secondary)
      }
      TrainingComparisonViewport(scenePath: checkpoint.url.path, camera: $comparisonCamera)
        .background(.black)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay {
          RoundedRectangle(cornerRadius: 10, style: .continuous)
            .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        }
    }
    .frame(maxWidth: .infinity)
  }

  private var processResult: some View {
    ReconstructionCard {
      VStack(alignment: .leading, spacing: 12) {
        sectionHeader("Process result", symbol: "terminal")
        ScrollView(.horizontal) {
          Text(model.transcript)
            .font(.caption.monospaced())
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12)
        .background(
          Color.black.opacity(0.82), in: RoundedRectangle(cornerRadius: 10, style: .continuous)
        )
        .foregroundStyle(.white.opacity(0.90))
      }
    }
  }
}
