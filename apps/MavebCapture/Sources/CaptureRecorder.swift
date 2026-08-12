import ARKit
import CryptoKit
import Foundation

final class CaptureRecorder: @unchecked Sendable {
  typealias StatusHandler = @Sendable (CaptureStatus) -> Void

  private let queue = DispatchQueue(
    label: "com.swayamsingal.maveb.capture.writer",
    qos: .userInitiated)
  private let stateLock = NSLock()
  private let maximumPendingFrames = 3
  private var pendingFrames = 0
  private var acceptingFrames = false
  private var manifest: CaptureManifest?
  private var rootURL: URL?
  private var status = CaptureStatus()
  private let statusHandler: StatusHandler

  init(statusHandler: @escaping StatusHandler) {
    self.statusHandler = statusHandler
  }

  @MainActor
  func start() throws -> URL {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let date = formatter.string(from: Date())
    let safeDate = date.replacingOccurrences(of: ":", with: "-")
    let root = try Self.captureRoot()
      .appendingPathComponent("MavebCapture-\(safeDate).mavebcapture", isDirectory: true)

    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    for directory in ["color", "depth", "confidence"] {
      try FileManager.default.createDirectory(
        at: root.appendingPathComponent(directory, isDirectory: true),
        withIntermediateDirectories: true
      )
    }

    let device = UIDevice.current
    let newManifest = CaptureManifest(
      sourceID: UUID().uuidString.lowercased(),
      createdAt: date,
      application: .init(),
      device: .init(
        model: Self.hardwareModel(),
        systemName: device.systemName,
        systemVersion: device.systemVersion),
      coordinateSystem: .init()
    )

    try CaptureJournal.initialize(newManifest, at: root)

    stateLock.lock()
    rootURL = root
    manifest = newManifest
    acceptingFrames = true
    status = CaptureStatus(recording: true, message: "Recording", packageURL: root)
    let snapshot = status
    stateLock.unlock()
    statusHandler(snapshot)
    return root
  }

  func append(frame: ARFrame, hostTimestampNanoseconds: UInt64) {
    stateLock.lock()
    guard acceptingFrames else {
      stateLock.unlock()
      return
    }
    guard pendingFrames < maximumPendingFrames else {
      manifest?.statistics.droppedFrames += 1
      status.droppedFrames += 1
      let snapshot = status
      stateLock.unlock()
      statusHandler(snapshot)
      return
    }
    pendingFrames += 1
    stateLock.unlock()

    queue.async { [self, frame, hostTimestampNanoseconds] in
      defer {
        stateLock.lock()
        pendingFrames -= 1
        stateLock.unlock()
      }
      do {
        try persist(
          frame: frame,
          hostTimestampNanoseconds: hostTimestampNanoseconds
        )
      } catch {
        stateLock.lock()
        manifest?.statistics.failedFrames += 1
        status.failedFrames += 1
        status.message = "Frame write failed: \(error.localizedDescription)"
        let snapshot = status
        stateLock.unlock()
        statusHandler(snapshot)
      }
    }
  }

  func pendingFrameCount() -> Int {
    stateLock.lock()
    defer { stateLock.unlock() }
    return pendingFrames
  }

  func reject(reason: CaptureAdmissionDecision.Reason) {
    stateLock.lock()
    if var currentManifest = manifest {
      currentManifest.statistics.admissionRejectedFrames =
        (currentManifest.statistics.admissionRejectedFrames ?? 0) + 1
      manifest = currentManifest
    }
    status.rejectedFrames += 1
    status.message = "Waiting for useful frame: \(reason.rawValue)"
    let snapshot = status
    stateLock.unlock()
    statusHandler(snapshot)
  }

  func stop(completion: @escaping @Sendable (Result<URL, Error>) -> Void) {
    stateLock.lock()
    acceptingFrames = false
    stateLock.unlock()

    queue.async { [self] in
      do {
        stateLock.lock()
        guard var finishedManifest = manifest, let root = rootURL else {
          stateLock.unlock()
          throw RecorderError.notRecording
        }
        finishedManifest.completedAt = CaptureJournal.timestamp()
        manifest = finishedManifest
        status.recording = false
        status.message = "Saved \(finishedManifest.frames.count) RGB-D frames"
        let snapshot = status
        stateLock.unlock()
        try CaptureJournal.finalize(finishedManifest, at: root)
        statusHandler(snapshot)
        completion(.success(root))
      } catch {
        completion(.failure(error))
      }
    }
  }

  private func persist(frame: ARFrame, hostTimestampNanoseconds: UInt64) throws {
    guard let sceneDepth = frame.sceneDepth else {
      throw RecorderError.missingSceneDepth
    }
    let color = frame.capturedImage
    guard CVPixelBufferGetPlaneCount(color) == 2 else {
      throw RecorderError.unsupportedColorFormat
    }

    stateLock.lock()
    guard var currentManifest = manifest, let root = rootURL else {
      stateLock.unlock()
      throw RecorderError.notRecording
    }
    let frameID = UInt64(currentManifest.frames.count + 1)
    stateLock.unlock()

    let stem = String(format: "%06llu", frameID)
    let luma = try Self.writePlane(
      buffer: color, plane: 0, pixelFormat: "y8",
      relativePath: "color/\(stem).y8", root: root
    )
    let chroma = try Self.writePlane(
      buffer: color, plane: 1, pixelFormat: "cbcr8x2",
      relativePath: "color/\(stem).cbcr8x2", root: root
    )
    let depth = try Self.writePlane(
      buffer: sceneDepth.depthMap, plane: nil, pixelFormat: "depth-f32-metres",
      relativePath: "depth/\(stem).f32", root: root
    )
    let confidence = try sceneDepth.confidenceMap.map {
      try Self.writePlane(
        buffer: $0, plane: nil, pixelFormat: "arkit-confidence-u8",
        relativePath: "confidence/\(stem).u8", root: root
      )
    }

    let imageWidth = CVPixelBufferGetWidth(color)
    let imageHeight = CVPixelBufferGetHeight(color)
    let depthWidth = CVPixelBufferGetWidth(sceneDepth.depthMap)
    let depthHeight = CVPixelBufferGetHeight(sceneDepth.depthMap)
    let imageIntrinsics = Self.flatten(frame.camera.intrinsics)
    let depthIntrinsics = Self.scaledIntrinsics(
      frame.camera.intrinsics,
      fromWidth: imageWidth,
      fromHeight: imageHeight,
      toWidth: depthWidth,
      toHeight: depthHeight
    )

    let entry = CaptureManifest.Frame(
      frameID: frameID,
      arTimestampSeconds: frame.timestamp,
      hostTimestampNanoseconds: hostTimestampNanoseconds,
      nativeImageOrientation: "landscapeRight",
      mirrored: false,
      cameraTrackingState: Self.trackingDescription(frame.camera.trackingState),
      cameraToWorld: Self.flatten(frame.camera.transform),
      calibration: .init(
        imageWidth: imageWidth,
        imageHeight: imageHeight,
        depthWidth: depthWidth,
        depthHeight: depthHeight,
        imageIntrinsics: imageIntrinsics,
        depthIntrinsics: Self.flatten(depthIntrinsics)
      ),
      luma: luma,
      chroma: chroma,
      depth: depth,
      confidence: confidence,
      exposure: .init(
        durationSeconds: frame.camera.exposureDuration,
        exposureOffsetEV: frame.camera.exposureOffset)
    )

    try CaptureJournal.append(entry, at: root)

    stateLock.lock()
    guard let frameCount = manifest?.frames.count, frameCount + 1 == Int(frameID) else {
      stateLock.unlock()
      throw RecorderError.frameOrdering
    }
    manifest?.frames.append(entry)
    manifest?.statistics.acceptedFrames += 1
    currentManifest = manifest!
    status.acceptedFrames = currentManifest.frames.count
    status.message = "Recording RGB + LiDAR"
    let snapshot = status
    stateLock.unlock()

    try CaptureJournal.writeCheckpoint(for: currentManifest, at: root)
    statusHandler(snapshot)
  }

  private static func writePlane(
    buffer: CVPixelBuffer,
    plane: Int?,
    pixelFormat: String,
    relativePath: String,
    root: URL
  ) throws -> CaptureManifest.Plane {
    CVPixelBufferLockBaseAddress(buffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }

    let width =
      plane.map { CVPixelBufferGetWidthOfPlane(buffer, $0) }
      ?? CVPixelBufferGetWidth(buffer)
    let height =
      plane.map { CVPixelBufferGetHeightOfPlane(buffer, $0) }
      ?? CVPixelBufferGetHeight(buffer)
    let stride =
      plane.map { CVPixelBufferGetBytesPerRowOfPlane(buffer, $0) }
      ?? CVPixelBufferGetBytesPerRow(buffer)
    let address =
      plane.flatMap { CVPixelBufferGetBaseAddressOfPlane(buffer, $0) }
      ?? CVPixelBufferGetBaseAddress(buffer)
    guard let address else { throw RecorderError.inaccessiblePlane }

    let activeBytesPerRow: Int
    switch pixelFormat {
    case "y8", "arkit-confidence-u8": activeBytesPerRow = width
    case "cbcr8x2": activeBytesPerRow = width * 2
    case "depth-f32-metres": activeBytesPerRow = width * MemoryLayout<Float>.size
    default: throw RecorderError.unsupportedPlaneFormat
    }
    guard activeBytesPerRow <= stride else {
      throw RecorderError.inaccessiblePlane
    }
    var bytes = Data(count: stride * height)
    bytes.withUnsafeMutableBytes { destination in
      guard let destinationBase = destination.baseAddress else { return }
      for row in 0..<height {
        memcpy(
          destinationBase.advanced(by: row * stride),
          address.advanced(by: row * stride),
          activeBytesPerRow)
      }
    }
    let destination = root.appendingPathComponent(relativePath)
    try bytes.write(to: destination, options: [.atomic])
    return .init(
      path: relativePath,
      sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
      width: width,
      height: height,
      rowStrideBytes: stride,
      pixelFormat: pixelFormat,
      byteCount: bytes.count)
  }

  static func recoverMostRecentInterruptedCapture() throws -> URL? {
    let root = try captureRoot()
    let captures = try FileManager.default.contentsOfDirectory(
      at: root,
      includingPropertiesForKeys: [.contentModificationDateKey, .isDirectoryKey],
      options: [.skipsHiddenFiles]
    ).filter {
      $0.pathExtension == "mavebcapture"
        && ((try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false)
    }.sorted {
      let left = try? $0.resourceValues(forKeys: [.contentModificationDateKey])
        .contentModificationDate
      let right = try? $1.resourceValues(forKeys: [.contentModificationDateKey])
        .contentModificationDate
      return (left ?? .distantPast) > (right ?? .distantPast)
    }
    for capture in captures {
      if try CaptureJournal.recover(at: capture) != nil {
        return capture
      }
    }
    return nil
  }

  private static func captureRoot() throws -> URL {
    guard
      let documents = FileManager.default.urls(
        for: .documentDirectory,
        in: .userDomainMask
      ).first
    else {
      throw RecorderError.missingDocumentsDirectory
    }
    let root = documents.appendingPathComponent("Captures", isDirectory: true)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
  }

  private static func hardwareModel() -> String {
    var systemInfo = utsname()
    uname(&systemInfo)
    return withUnsafePointer(to: &systemInfo.machine) {
      $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
    }
  }

  private static func flatten(_ matrix: simd_float3x3) -> [Float] {
    (0..<3).flatMap { column in (0..<3).map { row in matrix[column][row] } }
  }

  private static func flatten(_ matrix: simd_float4x4) -> [Float] {
    (0..<4).flatMap { column in (0..<4).map { row in matrix[column][row] } }
  }

  private static func scaledIntrinsics(
    _ intrinsics: simd_float3x3,
    fromWidth: Int,
    fromHeight: Int,
    toWidth: Int,
    toHeight: Int
  ) -> simd_float3x3 {
    var scaled = intrinsics
    let scaleX = Float(toWidth) / Float(fromWidth)
    let scaleY = Float(toHeight) / Float(fromHeight)
    scaled[0][0] *= scaleX
    scaled[1][1] *= scaleY
    scaled[2][0] *= scaleX
    scaled[2][1] *= scaleY
    return scaled
  }

  private static func trackingDescription(_ state: ARCamera.TrackingState) -> String {
    switch state {
    case .normal: return "normal"
    case .notAvailable: return "unavailable"
    case .limited(let reason): return "limited:\(reason)"
    }
  }

  enum RecorderError: LocalizedError {
    case notRecording
    case missingSceneDepth
    case unsupportedColorFormat
    case inaccessiblePlane
    case unsupportedPlaneFormat
    case missingDocumentsDirectory
    case frameOrdering

    var errorDescription: String? {
      switch self {
      case .notRecording: "Capture is not recording"
      case .missingSceneDepth: "ARKit did not provide scene depth"
      case .unsupportedColorFormat: "ARKit camera buffer is not bi-planar YUV"
      case .inaccessiblePlane: "A camera or depth plane could not be read"
      case .unsupportedPlaneFormat: "A camera or depth plane format is unsupported"
      case .missingDocumentsDirectory: "The app Documents directory is unavailable"
      case .frameOrdering: "The serialized frame order became inconsistent"
      }
    }
  }
}
