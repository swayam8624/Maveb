import Foundation

private func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
  guard condition() else { throw AdmissionTestError.failed(message) }
}

private func sample(
  time: Double,
  x: Double = 0,
  forwardX: Double = 0,
  clipped: Double = 0,
  sharpness: Double = 8,
  confidence: Double = 1,
  pending: Int = 0
) -> CaptureAdmissionSample {
  .init(
    timestampSeconds: time,
    position: .init(x: x, y: 0, z: 0),
    forward: .init(x: forwardX, y: 0, z: -1),
    sharpness: sharpness,
    clippedFraction: clipped,
    confidentDepthFraction: confidence,
    pendingWriterFrames: pending
  )
}

@main
private struct CaptureAdmissionTests {
  static func main() throws {
    var policy = CaptureAdmissionPolicy()
    try require(policy.evaluate(sample(time: 0)).reason == .firstFrame, "first frame is accepted")

    let rateLimited = policy.evaluate(sample(time: 0.02, x: 0.1))
    try require(!rateLimited.accepted && rateLimited.reason == .rateLimited, "15 Hz is bounded")

    let moved = policy.evaluate(sample(time: 0.1, x: 0.02))
    try require(moved.accepted && moved.reason == .usefulMotion, "useful translation is accepted")

    let staticFrame = policy.evaluate(sample(time: 0.2, x: 0.02))
    try require(
      !staticFrame.accepted && staticFrame.reason == .insufficientMotion,
      "redundant stationary frames are filtered"
    )

    let refresh = policy.evaluate(sample(time: 0.7, x: 0.02))
    try require(
      refresh.accepted && refresh.reason == .stationaryRefresh, "stationary view refreshes")

    try require(
      policy.evaluate(sample(time: 0.8, x: 0.05, clipped: 0.99)).reason == .extremeExposure,
      "almost fully clipped frames are rejected"
    )
    try require(
      policy.evaluate(sample(time: 0.8, x: 0.05, confidence: 0.1)).reason == .unusableDepth,
      "low-confidence depth is rejected"
    )
    try require(
      policy.evaluate(sample(time: 0.8, x: 0.05, sharpness: 0.1)).reason == .unusablySoft,
      "unusably soft frames are rejected"
    )
    try require(
      policy.evaluate(sample(time: 0.8, x: 0.05, pending: 3)).reason == .writerPressure,
      "writer pressure applies backpressure before enqueue"
    )

    policy.reset()
    try require(policy.evaluate(sample(time: 10)).reason == .firstFrame, "reset starts a new scan")
    print("CaptureAdmissionTests passed")
  }
}

private enum AdmissionTestError: LocalizedError {
  case failed(String)

  var errorDescription: String? {
    switch self {
    case .failed(let message): message
    }
  }
}
