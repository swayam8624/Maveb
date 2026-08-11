import CryptoKit
import Darwin
import Foundation
import RealityKit

private struct Options {
  var input: URL
  var output: URL
  var detail = PhotogrammetrySession.Request.Detail.medium
  var detailName = "medium"
  var sampleOrdering = PhotogrammetrySession.Configuration.SampleOrdering.unordered
  var sampleOrderingName = "unordered"
  var featureSensitivity = PhotogrammetrySession.Configuration.FeatureSensitivity.normal
  var featureSensitivityName = "normal"
  var objectMasking = false
  var checkpoint: URL?
  var manifest: URL?
  var json = false
  var dryRun = false
}

private struct InputRecord: Codable {
  let path: String
  let byteCount: UInt64
  let sha256: String
}

private struct Provenance: Codable {
  let schemaVersion: Int
  let generator: String
  let generatedAt: String
  let operatingSystem: String
  let inputDirectory: String
  let outputModel: String
  let detail: String
  let sampleOrdering: String
  let featureSensitivity: String
  let objectMasking: Bool
  let inputs: [InputRecord]
  let invalidSamples: [String]
  let skippedSamples: [Int]
}

private enum ToolError: LocalizedError {
  case usage(String)
  case unsupported
  case invalidInput(String)
  case processing(String)

  var errorDescription: String? {
    switch self {
    case .usage(let message), .invalidInput(let message), .processing(let message):
      return message
    case .unsupported:
      return "Apple photogrammetry is not supported on this Mac"
    }
  }
}

private func printHelp() {
  print(
    """
    Usage: maveb-photogrammetry <images-directory> --output <model.usdz> [options]

    Builds a local textured USDZ with Apple's PhotogrammetrySession and writes
    a provenance manifest containing deterministic input hashes.

    Options:
      --detail preview|reduced|medium|full|raw
      --ordering unordered|sequential
      --sensitivity normal|high
      --object-masking
      --checkpoint <directory>
      --manifest <path>
      --dry-run
      --json
      --help
    """)
}

private func parseOptions(_ arguments: [String]) throws -> Options {
  if arguments.count == 1 && arguments[0] == "--help" {
    printHelp()
    Darwin.exit(EXIT_SUCCESS)
  }
  guard !arguments.isEmpty else { throw ToolError.usage("Missing images directory") }
  let input = URL(fileURLWithPath: arguments[0]).standardizedFileURL
  var output: URL?
  var options = Options(input: input, output: URL(fileURLWithPath: "/dev/null"))
  var index = 1
  while index < arguments.count {
    let argument = arguments[index]
    func value() throws -> String {
      guard index + 1 < arguments.count else {
        throw ToolError.usage("Missing value for \(argument)")
      }
      index += 1
      return arguments[index]
    }
    switch argument {
    case "--output": output = URL(fileURLWithPath: try value()).standardizedFileURL
    case "--manifest": options.manifest = URL(fileURLWithPath: try value()).standardizedFileURL
    case "--checkpoint": options.checkpoint = URL(fileURLWithPath: try value()).standardizedFileURL
    case "--detail":
      options.detailName = try value()
      switch options.detailName {
      case "preview": options.detail = .preview
      case "reduced": options.detail = .reduced
      case "medium": options.detail = .medium
      case "full": options.detail = .full
      case "raw": options.detail = .raw
      default: throw ToolError.usage("Unknown detail: \(options.detailName)")
      }
    case "--ordering":
      options.sampleOrderingName = try value()
      switch options.sampleOrderingName {
      case "unordered": options.sampleOrdering = .unordered
      case "sequential": options.sampleOrdering = .sequential
      default: throw ToolError.usage("Unknown ordering: \(options.sampleOrderingName)")
      }
    case "--sensitivity":
      options.featureSensitivityName = try value()
      switch options.featureSensitivityName {
      case "normal": options.featureSensitivity = .normal
      case "high": options.featureSensitivity = .high
      default: throw ToolError.usage("Unknown sensitivity: \(options.featureSensitivityName)")
      }
    case "--object-masking": options.objectMasking = true
    case "--dry-run": options.dryRun = true
    case "--json": options.json = true
    default: throw ToolError.usage("Unknown option: \(argument)")
    }
    index += 1
  }
  guard let output else { throw ToolError.usage("--output is required") }
  guard output.pathExtension.lowercased() == "usdz" else {
    throw ToolError.usage("Output must use the .usdz extension")
  }
  options.output = output
  if options.manifest == nil {
    options.manifest = output.deletingPathExtension().appendingPathExtension("photogrammetry.json")
  }
  return options
}

private let imageExtensions: Set<String> = ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff"]

private func imageURLs(in directory: URL) throws -> [URL] {
  var isDirectory: ObjCBool = false
  guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory),
    isDirectory.boolValue
  else {
    throw ToolError.invalidInput("Input is not an images directory: \(directory.path)")
  }
  let urls = try FileManager.default.contentsOfDirectory(
    at: directory,
    includingPropertiesForKeys: [.isRegularFileKey],
    options: [.skipsHiddenFiles]
  ).filter {
    imageExtensions.contains($0.pathExtension.lowercased())
      && ((try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) ?? false)
  }.sorted {
    $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending
  }
  guard urls.count >= 3 else {
    throw ToolError.invalidInput("Photogrammetry requires at least three supported images")
  }
  return urls
}

private func sha256(_ url: URL) throws -> String {
  let handle = try FileHandle(forReadingFrom: url)
  defer { try? handle.close() }
  var digest = SHA256()
  while let data = try handle.read(upToCount: 4 * 1024 * 1024), !data.isEmpty {
    digest.update(data: data)
  }
  return digest.finalize().map { String(format: "%02x", $0) }.joined()
}

private func records(for images: [URL], relativeTo root: URL) throws -> [InputRecord] {
  try images.map { url in
    let values = try url.resourceValues(forKeys: [.fileSizeKey])
    return InputRecord(
      path: url.path.replacingOccurrences(of: root.path + "/", with: ""),
      byteCount: UInt64(values.fileSize ?? 0),
      sha256: try sha256(url)
    )
  }
}

private func writeJSON(_ value: some Encodable, to url: URL) throws {
  let encoder = JSONEncoder()
  encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
  encoder.dateEncodingStrategy = .iso8601
  let data = try encoder.encode(value)
  try FileManager.default.createDirectory(
    at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
  try data.write(to: url, options: .atomic)
}

private func emitJSON(_ object: [String: Any], to stream: FileHandle = .standardOutput) {
  guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
  else { return }
  stream.write(data)
  stream.write(Data([0x0a]))
}

@main
private struct MavebPhotogrammetry {
  static func main() async {
    do {
      let options = try parseOptions(Array(CommandLine.arguments.dropFirst()))
      guard PhotogrammetrySession.isSupported else { throw ToolError.unsupported }
      let images = try imageURLs(in: options.input)
      let inputs = try records(for: images, relativeTo: options.input)
      if options.dryRun {
        emitJSON([
          "ok": true, "dryRun": true, "images": images.count,
          "input": options.input.path, "output": options.output.path,
          "detail": options.detailName,
        ])
        return
      }

      try FileManager.default.createDirectory(
        at: options.output.deletingLastPathComponent(), withIntermediateDirectories: true)
      if let checkpoint = options.checkpoint {
        try FileManager.default.createDirectory(at: checkpoint, withIntermediateDirectories: true)
      }
      let temporary = options.output.deletingLastPathComponent().appendingPathComponent(
        ".\(options.output.lastPathComponent).\(UUID().uuidString).tmp.usdz")
      defer { try? FileManager.default.removeItem(at: temporary) }

      var configuration: PhotogrammetrySession.Configuration
      if let checkpoint = options.checkpoint {
        configuration = .init(checkpointDirectory: checkpoint)
      } else {
        configuration = .init()
      }
      configuration.sampleOrdering = options.sampleOrdering
      configuration.featureSensitivity = options.featureSensitivity
      configuration.isObjectMaskingEnabled = options.objectMasking
      let session = try PhotogrammetrySession(input: options.input, configuration: configuration)
      let request = PhotogrammetrySession.Request.modelFile(url: temporary, detail: options.detail)
      try session.process(requests: [request])

      var requestCompleted = false
      var invalidSamples: [String] = []
      var skippedSamples: [Int] = []
      for try await output in session.outputs {
        switch output {
        case .requestProgress(_, let fraction):
          FileHandle.standardError.write(
            Data(String(format: "photogrammetry %.1f%%\n", fraction * 100).utf8))
        case .requestProgressInfo(_, let info):
          if let stage = info.processingStage {
            FileHandle.standardError.write(
              Data("photogrammetry stage \(String(describing: stage))\n".utf8))
          }
        case .requestComplete(_, .modelFile): requestCompleted = true
        case .requestError(_, let error): throw ToolError.processing(error.localizedDescription)
        case .invalidSample(let id, let reason): invalidSamples.append("\(id): \(reason)")
        case .skippedSample(let id): skippedSamples.append(id)
        case .processingCancelled: throw ToolError.processing("Photogrammetry was cancelled")
        case .processingComplete: break
        default: break
        }
        if case .processingComplete = output { break }
      }
      guard requestCompleted, FileManager.default.fileExists(atPath: temporary.path) else {
        throw ToolError.processing("Photogrammetry completed without producing a model")
      }
      if FileManager.default.fileExists(atPath: options.output.path) {
        _ = try FileManager.default.replaceItemAt(options.output, withItemAt: temporary)
      } else {
        try FileManager.default.moveItem(at: temporary, to: options.output)
      }

      let formatter = ISO8601DateFormatter()
      let provenance = Provenance(
        schemaVersion: 1,
        generator: "maveb-photogrammetry",
        generatedAt: formatter.string(from: Date()),
        operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString,
        inputDirectory: options.input.path,
        outputModel: options.output.path,
        detail: options.detailName,
        sampleOrdering: options.sampleOrderingName,
        featureSensitivity: options.featureSensitivityName,
        objectMasking: options.objectMasking,
        inputs: inputs,
        invalidSamples: invalidSamples,
        skippedSamples: skippedSamples
      )
      try writeJSON(provenance, to: options.manifest!)
      emitJSON([
        "ok": true, "images": images.count, "output": options.output.path,
        "manifest": options.manifest!.path, "detail": options.detailName,
        "invalidSamples": invalidSamples.count, "skippedSamples": skippedSamples.count,
      ])
    } catch {
      emitJSON(["ok": false, "error": error.localizedDescription], to: .standardError)
      Darwin.exit(EXIT_FAILURE)
    }
  }
}
