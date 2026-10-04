import Foundation

struct CaptureAdmissionSample: Sendable {
  struct Vector: Sendable {
    var x: Double
    var y: Double
    var z: Double

    static func distance(_ left: Vector, _ right: Vector) -> Double {
      let x = left.x - right.x
      let y = left.y - right.y
      let z = left.z - right.z
      return (x * x + y * y + z * z).squareRoot()
    }

    static func angle(_ left: Vector, _ right: Vector) -> Double {
      let leftLength = (left.x * left.x + left.y * left.y + left.z * left.z).squareRoot()
      let rightLength = (right.x * right.x + right.y * right.y + right.z * right.z).squareRoot()
      guard leftLength > 0, rightLength > 0 else { return 0 }
      let dot =
        (left.x * right.x + left.y * right.y + left.z * right.z)
        / (leftLength * rightLength)
      return acos(min(1, max(-1, dot)))
    }
  }

  var timestampSeconds: Double
  var position: Vector
  var forward: Vector
  var sharpness: Double
  var clippedFraction: Double
  var confidentDepthFraction: Double
  var pendingWriterFrames: Int
}

struct CaptureAdmissionDecision: Sendable {
  enum Reason: String, Sendable {
    case firstFrame = "first-frame"
    case usefulMotion = "useful-motion"
    case stationaryRefresh = "stationary-refresh"
    case writerPressure = "writer-pressure"
    case rateLimited = "rate-limited"
    case insufficientMotion = "insufficient-motion"
    case unusableDepth = "unusable-depth"
    case extremeExposure = "extreme-exposure"
    case unusablySoft = "unusably-soft"
  }

  var accepted: Bool
  var reason: Reason
}

struct CaptureAdmissionPolicy: Sendable {
  var minimumIntervalSeconds = 1.0 / 15.0
  var stationaryIntervalSeconds = 0.5
  var minimumTranslationMetres = 0.015
  var minimumRotationRadians = 2.0 * .pi / 180.0
  var minimumSharpness = 0.25
  var maximumClippedFraction = 0.95
  var minimumConfidentDepthFraction = 0.2
  var maximumPendingWriterFrames = 2

  private var lastAccepted: CaptureAdmissionSample?

  mutating func reset() {
    lastAccepted = nil
  }

  mutating func evaluate(_ sample: CaptureAdmissionSample) -> CaptureAdmissionDecision {
    guard sample.pendingWriterFrames <= maximumPendingWriterFrames else {
      return .init(accepted: false, reason: .writerPressure)
    }
    guard sample.confidentDepthFraction >= minimumConfidentDepthFraction else {
      return .init(accepted: false, reason: .unusableDepth)
    }
    guard sample.clippedFraction <= maximumClippedFraction else {
      return .init(accepted: false, reason: .extremeExposure)
    }
    guard sample.sharpness >= minimumSharpness else {
      return .init(accepted: false, reason: .unusablySoft)
    }
    guard let previous = lastAccepted else {
      lastAccepted = sample
      return .init(accepted: true, reason: .firstFrame)
    }

    let elapsed = sample.timestampSeconds - previous.timestampSeconds
    guard elapsed >= minimumIntervalSeconds else {
      return .init(accepted: false, reason: .rateLimited)
    }
    let translation = CaptureAdmissionSample.Vector.distance(sample.position, previous.position)
    let rotation = CaptureAdmissionSample.Vector.angle(sample.forward, previous.forward)
    if translation >= minimumTranslationMetres || rotation >= minimumRotationRadians {
      lastAccepted = sample
      return .init(accepted: true, reason: .usefulMotion)
    }
    if elapsed >= stationaryIntervalSeconds {
      lastAccepted = sample
      return .init(accepted: true, reason: .stationaryRefresh)
    }
    return .init(accepted: false, reason: .insufficientMotion)
  }
}
