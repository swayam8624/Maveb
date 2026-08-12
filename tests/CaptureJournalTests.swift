import CryptoKit
import Foundation

private enum TestError: LocalizedError {
  case failed(String)

  var errorDescription: String? {
    switch self {
    case .failed(let message): message
    }
  }
}

private func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
  guard condition() else {
    throw TestError.failed(message)
  }
}

private func plane(path: String, data: Data, root: URL) throws -> CaptureManifest.Plane {
  let url = root.appendingPathComponent(path)
  try FileManager.default.createDirectory(
    at: url.deletingLastPathComponent(),
    withIntermediateDirectories: true
  )
  try data.write(to: url, options: [.atomic])
  return .init(
    path: path,
    sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
    width: data.count,
    height: 1,
    rowStrideBytes: data.count,
    pixelFormat: "fixture",
    byteCount: data.count
  )
}

private func frame(id: UInt64, timestamp: UInt64, root: URL) throws -> CaptureManifest.Frame {
  let stem = String(format: "%06llu", id)
  return .init(
    frameID: id,
    arTimestampSeconds: Double(id),
    hostTimestampNanoseconds: timestamp,
    nativeImageOrientation: "landscapeRight",
    mirrored: false,
    cameraTrackingState: "normal",
    cameraToWorld: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    calibration: .init(
      imageWidth: 1,
      imageHeight: 1,
      depthWidth: 1,
      depthHeight: 1,
      imageIntrinsics: [1, 0, 0, 0, 1, 0, 0, 0, 1],
      depthIntrinsics: [1, 0, 0, 0, 1, 0, 0, 0, 1]
    ),
    luma: try plane(path: "color/\(stem).y8", data: Data([1]), root: root),
    chroma: try plane(path: "color/\(stem).cbcr8x2", data: Data([2, 3]), root: root),
    depth: try plane(path: "depth/\(stem).f32", data: Data([4, 5, 6, 7]), root: root),
    confidence: try plane(path: "confidence/\(stem).u8", data: Data([2]), root: root),
    exposure: .init(durationSeconds: 0.01, exposureOffsetEV: 0)
  )
}

private func manifest() -> CaptureManifest {
  CaptureManifest(
    sourceID: "capture-journal-fixture",
    createdAt: "2026-08-12T00:00:00.000Z",
    application: .init(),
    device: .init(model: "fixture", systemName: "test", systemVersion: "1"),
    coordinateSystem: .init()
  )
}

@main
private struct CaptureJournalTests {
  static func main() throws {
    let root = FileManager.default.temporaryDirectory
      .appendingPathComponent("maveb-capture-journal-tests-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: root) }
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

    var current = manifest()
    try CaptureJournal.initialize(current, at: root)
    let first = try frame(id: 1, timestamp: 1_000, root: root)
    try CaptureJournal.append(first, at: root)
    current.frames.append(first)
    current.statistics.acceptedFrames = 1
    current.statistics.droppedFrames = 4
    try CaptureJournal.writeCheckpoint(for: current, at: root)

    let second = try frame(id: 2, timestamp: 2_000, root: root)
    try CaptureJournal.append(second, at: root)
    current.frames.append(second)
    current.statistics.acceptedFrames = 2
    try CaptureJournal.writeCheckpoint(for: current, at: root)

    let journalURL = root.appendingPathComponent(CaptureJournal.journalName)
    let handle = try FileHandle(forWritingTo: journalURL)
    try handle.seekToEnd()
    try handle.write(contentsOf: Data(#"{"frameID":3"#.utf8))
    try handle.close()

    let recovered = try CaptureJournal.recover(at: root)
    try require(recovered?.frames.map(\.frameID) == [1, 2], "complete journal frames recover")
    try require(recovered?.statistics.acceptedFrames == 2, "accepted count is rebuilt")
    try require(recovered?.statistics.droppedFrames == 4, "checkpoint statistics survive")
    try require(
      recovered?.recovery?.discardedTrailingBytes == 12,
      "only the torn final record is discarded"
    )
    try require(
      !FileManager.default.fileExists(atPath: journalURL.path),
      "recovery compacts and removes the journal"
    )

    let decoded = try JSONDecoder().decode(
      CaptureManifest.self,
      from: Data(contentsOf: root.appendingPathComponent(CaptureJournal.manifestName))
    )
    try require(decoded.completedAt != nil, "recovered manifest is finalized")
    try require(decoded.frames.count == 2, "canonical manifest contains recovered frames")

    let damagedRoot = root.appendingPathComponent("damaged.mavebcapture")
    try FileManager.default.createDirectory(at: damagedRoot, withIntermediateDirectories: true)
    var damagedManifest = manifest()
    try CaptureJournal.initialize(damagedManifest, at: damagedRoot)
    let damagedFrame = try frame(id: 1, timestamp: 1_000, root: damagedRoot)
    try CaptureJournal.append(damagedFrame, at: damagedRoot)
    damagedManifest.frames.append(damagedFrame)
    damagedManifest.statistics.acceptedFrames = 1
    try CaptureJournal.writeCheckpoint(for: damagedManifest, at: damagedRoot)
    try Data([9]).write(
      to: damagedRoot.appendingPathComponent(damagedFrame.luma.path),
      options: [.atomic]
    )
    do {
      _ = try CaptureJournal.recover(at: damagedRoot)
      throw TestError.failed("recovery must reject a plane whose hash changed")
    } catch is CaptureJournal.JournalError {
      // Expected: committed journal entries cannot hide damaged plane data.
    }
    print("CaptureJournalTests passed")
  }

}
