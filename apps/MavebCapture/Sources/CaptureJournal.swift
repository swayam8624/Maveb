import CryptoKit
import Foundation

enum CaptureJournal {
  static let journalName = "frames.ndjson"
  static let checkpointName = "checkpoint.json"
  static let manifestName = "manifest.json"

  private struct Checkpoint: Codable {
    var schemaVersion = 1
    var sourceID: String
    var updatedAt: String
    var lastCommittedFrameID: UInt64
    var statistics: CaptureManifest.Statistics
  }

  static func initialize(_ manifest: CaptureManifest, at root: URL) throws {
    var header = manifest
    header.frames = []
    header.completedAt = nil
    header.recovery = nil
    try writeManifest(header, at: root)
    try Data().write(
      to: root.appendingPathComponent(journalName),
      options: [.atomic]
    )
    try writeCheckpoint(for: header, at: root)
  }

  static func append(_ frame: CaptureManifest.Frame, at root: URL) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    var record = try encoder.encode(frame)
    record.append(0x0A)

    let url = root.appendingPathComponent(journalName)
    let handle = try FileHandle(forWritingTo: url)
    defer { try? handle.close() }
    try handle.seekToEnd()
    try handle.write(contentsOf: record)
    try handle.synchronize()
  }

  static func writeCheckpoint(for manifest: CaptureManifest, at root: URL) throws {
    let checkpoint = Checkpoint(
      sourceID: manifest.sourceID,
      updatedAt: timestamp(),
      lastCommittedFrameID: manifest.frames.last?.frameID ?? 0,
      statistics: manifest.statistics
    )
    try writeJSON(checkpoint, to: root.appendingPathComponent(checkpointName))
  }

  static func finalize(_ manifest: CaptureManifest, at root: URL) throws {
    try writeManifest(manifest, at: root)
    try? FileManager.default.removeItem(at: root.appendingPathComponent(journalName))
    try? FileManager.default.removeItem(at: root.appendingPathComponent(checkpointName))
  }

  @discardableResult
  static func recover(at root: URL) throws -> CaptureManifest? {
    let manifestURL = root.appendingPathComponent(manifestName)
    let decoder = JSONDecoder()
    var manifest = try decoder.decode(
      CaptureManifest.self,
      from: Data(contentsOf: manifestURL)
    )
    guard manifest.completedAt == nil else {
      try? FileManager.default.removeItem(at: root.appendingPathComponent(journalName))
      try? FileManager.default.removeItem(at: root.appendingPathComponent(checkpointName))
      return nil
    }

    let journalURL = root.appendingPathComponent(journalName)
    guard FileManager.default.fileExists(atPath: journalURL.path) else { return nil }
    let data = try Data(contentsOf: journalURL, options: [.mappedIfSafe])
    guard let finalNewline = data.lastIndex(of: 0x0A) else { return nil }
    let completeEnd = data.index(after: finalNewline)
    let completeData = data[..<completeEnd]
    let trailingBytes = data.distance(from: completeEnd, to: data.endIndex)

    var frames: [CaptureManifest.Frame] = []
    for line in completeData.split(separator: 0x0A, omittingEmptySubsequences: true) {
      frames.append(try decoder.decode(CaptureManifest.Frame.self, from: Data(line)))
    }
    guard !frames.isEmpty else { return nil }
    try validate(frames: frames, at: root)

    if let checkpoint = try? decoder.decode(
      Checkpoint.self,
      from: Data(contentsOf: root.appendingPathComponent(checkpointName))
    ), checkpoint.sourceID == manifest.sourceID {
      manifest.statistics = checkpoint.statistics
    }
    manifest.frames = frames
    manifest.statistics.acceptedFrames = frames.count
    manifest.completedAt = timestamp()
    manifest.recovery = .init(
      recoveredAt: manifest.completedAt!,
      journalFrames: frames.count,
      discardedTrailingBytes: trailingBytes
    )
    try finalize(manifest, at: root)
    return manifest
  }

  private static func validate(frames: [CaptureManifest.Frame], at root: URL) throws {
    var previousID: UInt64 = 0
    var previousHostTimestamp: UInt64 = 0
    var paths = Set<String>()
    for frame in frames {
      guard frame.frameID == previousID + 1,
        frame.hostTimestampNanoseconds >= previousHostTimestamp
      else {
        throw JournalError.frameOrdering
      }
      for plane in [frame.luma, frame.chroma, frame.depth] + [frame.confidence].compactMap({ $0 }) {
        try validate(plane: plane, at: root, paths: &paths)
      }
      previousID = frame.frameID
      previousHostTimestamp = frame.hostTimestampNanoseconds
    }
  }

  private static func validate(
    plane: CaptureManifest.Plane,
    at root: URL,
    paths: inout Set<String>
  ) throws {
    guard !plane.path.isEmpty,
      !plane.path.hasPrefix("/"),
      !plane.path.split(separator: "/").contains(".."),
      paths.insert(plane.path).inserted
    else {
      throw JournalError.invalidPlane(plane.path)
    }
    let url = root.appendingPathComponent(plane.path).standardizedFileURL
    guard url.path.hasPrefix(root.standardizedFileURL.path + "/") else {
      throw JournalError.invalidPlane(plane.path)
    }
    let data = try Data(contentsOf: url, options: [.mappedIfSafe])
    guard data.count == plane.byteCount,
      SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined()
        == plane.sha256
    else {
      throw JournalError.invalidPlane(plane.path)
    }
  }

  private static func writeManifest(_ manifest: CaptureManifest, at root: URL) throws {
    try writeJSON(manifest, to: root.appendingPathComponent(manifestName))
  }

  private static func writeJSON(_ value: some Encodable, to url: URL) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    try encoder.encode(value).write(to: url, options: [.atomic])
  }

  static func timestamp() -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.string(from: Date())
  }

  enum JournalError: LocalizedError {
    case frameOrdering
    case invalidPlane(String)

    var errorDescription: String? {
      switch self {
      case .frameOrdering:
        "Recovered frame IDs or callback timestamps are not ordered"
      case .invalidPlane(let path):
        "Recovered capture plane is missing, damaged, or unsafe: \(path)"
      }
    }
  }
}
