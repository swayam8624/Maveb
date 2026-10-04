import Foundation

struct CaptureManifest: Codable, Sendable {
  static let schemaVersion = 2

  var schemaVersion = CaptureManifest.schemaVersion
  var sourceID: String
  var createdAt: String
  var completedAt: String?
  var application: Application
  var device: Device
  var coordinateSystem: CoordinateSystem
  var frames: [Frame] = []
  var statistics = Statistics()
  var recovery: Recovery?

  struct Application: Codable, Sendable {
    var name = "MavebCapture"
    var version = "0.1.0"
  }

  struct Device: Codable, Sendable {
    var model: String
    var systemName: String
    var systemVersion: String
  }

  struct CoordinateSystem: Codable, Sendable {
    var camera = "ARKit right-handed: +X right, +Y up, -Z forward"
    var pose = "column-major camera-to-world 4x4 matrix"
    var depthUnit = "metres"
    var intrinsics = "3x3 column-major pixels"
  }

  struct Plane: Codable, Sendable {
    var path: String
    var sha256: String
    var width: Int
    var height: Int
    var rowStrideBytes: Int
    var pixelFormat: String
    var byteCount: Int
  }

  struct Calibration: Codable, Sendable {
    var imageWidth: Int
    var imageHeight: Int
    var depthWidth: Int
    var depthHeight: Int
    var imageIntrinsics: [Float]
    var depthIntrinsics: [Float]
  }

  struct Exposure: Codable, Sendable {
    var durationSeconds: Double
    var exposureOffsetEV: Float
  }

  struct Frame: Codable, Sendable {
    var frameID: UInt64
    var arTimestampSeconds: Double
    var hostTimestampNanoseconds: UInt64
    var nativeImageOrientation: String
    var mirrored: Bool
    var cameraTrackingState: String
    var cameraToWorld: [Float]
    var calibration: Calibration
    var luma: Plane
    var chroma: Plane
    var depth: Plane
    var confidence: Plane?
    var exposure: Exposure
  }

  struct Statistics: Codable, Sendable {
    var acceptedFrames = 0
    var droppedFrames = 0
    var failedFrames = 0
    var admissionRejectedFrames: Int?
  }

  struct Recovery: Codable, Sendable {
    var recoveredAt: String
    var journalFrames: Int
    var discardedTrailingBytes: Int
  }
}

struct CaptureStatus: Sendable {
  var recording = false
  var acceptedFrames = 0
  var droppedFrames = 0
  var failedFrames = 0
  var rejectedFrames = 0
  var message = "Ready"
  var packageURL: URL?
}
