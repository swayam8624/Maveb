import ARKit
import AVFoundation
import Foundation
import SwiftUI

@MainActor
final class CaptureController: NSObject, ObservableObject {
  @Published private(set) var status = CaptureStatus()
  @Published private(set) var trackingState = "Unavailable"
  @Published private(set) var lidarSupported = false
  @Published private(set) var lastError: String?

  let session = ARSession()
  private lazy var recorder = CaptureRecorder { [weak self] status in
    Task { @MainActor in self?.status = status }
  }
  private var admissionPolicy = CaptureAdmissionPolicy()
  private var attemptedRecovery = false

  override init() {
    super.init()
    session.delegate = self
    lidarSupported =
      ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
      && ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
  }

  func startSession() {
    if !attemptedRecovery {
      attemptedRecovery = true
      do {
        if let recovered = try CaptureRecorder.recoverMostRecentInterruptedCapture() {
          status = CaptureStatus(
            message: "Recovered interrupted RGB-D capture",
            packageURL: recovered
          )
        }
      } catch {
        lastError = "Capture recovery failed: \(error.localizedDescription)"
      }
    }
    guard lidarSupported else {
      lastError = "This device does not support ARKit scene depth and reconstruction."
      return
    }
    let configuration = ARWorldTrackingConfiguration()
    configuration.frameSemantics.insert(.sceneDepth)
    configuration.sceneReconstruction = .meshWithClassification
    configuration.worldAlignment = .gravity
    configuration.environmentTexturing = .automatic
    session.run(
      configuration,
      options: [
        .resetTracking, .removeExistingAnchors,
        .resetSceneReconstruction,
      ])
  }

  func startRecording() {
    guard lidarSupported else { return }
    do {
      _ = try recorder.start()
      admissionPolicy.reset()
      lastError = nil
    } catch {
      lastError = error.localizedDescription
    }
  }

  func stopRecording() {
    recorder.stop { [weak self] result in
      if case .failure(let error) = result {
        Task { @MainActor in self?.lastError = error.localizedDescription }
      }
    }
  }
}

extension CaptureController: ARSessionDelegate {
  nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
    let hostTimestampNanoseconds = DispatchTime.now().uptimeNanoseconds
    Task { @MainActor [weak self] in
      guard let self else { return }
      trackingState = Self.describe(frame.camera.trackingState)
      guard status.recording,
        case .normal = frame.camera.trackingState,
        let sceneDepth = frame.sceneDepth
      else { return }

      let quality = Self.measureQuality(frame: frame, sceneDepth: sceneDepth)
      let transform = frame.camera.transform
      let decision = admissionPolicy.evaluate(
        .init(
          timestampSeconds: frame.timestamp,
          position: .init(
            x: Double(transform.columns.3.x),
            y: Double(transform.columns.3.y),
            z: Double(transform.columns.3.z)
          ),
          forward: .init(
            x: -Double(transform.columns.2.x),
            y: -Double(transform.columns.2.y),
            z: -Double(transform.columns.2.z)
          ),
          sharpness: quality.sharpness,
          clippedFraction: quality.clippedFraction,
          confidentDepthFraction: quality.confidentDepthFraction,
          pendingWriterFrames: recorder.pendingFrameCount()
        )
      )
      guard decision.accepted else {
        recorder.reject(reason: decision.reason)
        return
      }
      recorder.append(
        frame: frame,
        hostTimestampNanoseconds: hostTimestampNanoseconds
      )
    }
  }

  nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
    Task { @MainActor [weak self] in self?.lastError = error.localizedDescription }
  }

  nonisolated func sessionWasInterrupted(_ session: ARSession) {
    Task { @MainActor [weak self] in self?.lastError = "AR session interrupted" }
  }

  private static func describe(_ state: ARCamera.TrackingState) -> String {
    switch state {
    case .normal: "Normal"
    case .notAvailable: "Unavailable"
    case .limited(let reason): "Limited: \(reason)"
    }
  }

  private static func measureQuality(
    frame: ARFrame,
    sceneDepth: ARDepthData
  ) -> (sharpness: Double, clippedFraction: Double, confidentDepthFraction: Double) {
    let color = frame.capturedImage
    CVPixelBufferLockBaseAddress(color, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(color, .readOnly) }

    var sharpness = 0.0
    var clipped = 0
    var samples = 0
    if CVPixelBufferGetPlaneCount(color) >= 1,
      let base = CVPixelBufferGetBaseAddressOfPlane(color, 0)
    {
      let width = CVPixelBufferGetWidthOfPlane(color, 0)
      let height = CVPixelBufferGetHeightOfPlane(color, 0)
      let rowStride = CVPixelBufferGetBytesPerRowOfPlane(color, 0)
      let step = max(1, min(width, height) / 64)
      for y in stride(from: step, to: height, by: step) {
        let row = base.advanced(by: y * rowStride).assumingMemoryBound(to: UInt8.self)
        let prior = base.advanced(by: (y - step) * rowStride).assumingMemoryBound(to: UInt8.self)
        for x in stride(from: step, to: width, by: step) {
          let value = Int(row[x])
          sharpness += Double(abs(value - Int(row[x - step])) + abs(value - Int(prior[x])))
          if value <= 18 || value >= 233 { clipped += 1 }
          samples += 1
        }
      }
    }

    var confident = 0
    var depthSamples = 0
    if let confidence = sceneDepth.confidenceMap {
      CVPixelBufferLockBaseAddress(confidence, .readOnly)
      defer { CVPixelBufferUnlockBaseAddress(confidence, .readOnly) }
      if let base = CVPixelBufferGetBaseAddress(confidence) {
        let width = CVPixelBufferGetWidth(confidence)
        let height = CVPixelBufferGetHeight(confidence)
        let rowStride = CVPixelBufferGetBytesPerRow(confidence)
        let step = max(1, min(width, height) / 64)
        for y in stride(from: 0, to: height, by: step) {
          let row = base.advanced(by: y * rowStride).assumingMemoryBound(to: UInt8.self)
          for x in stride(from: 0, to: width, by: step) {
            if row[x] >= 1 { confident += 1 }
            depthSamples += 1
          }
        }
      }
    } else {
      confident = 1
      depthSamples = 1
    }

    return (
      samples > 0 ? sharpness / Double(samples * 2) : 0,
      samples > 0 ? Double(clipped) / Double(samples) : 1,
      depthSamples > 0 ? Double(confident) / Double(depthSamples) : 0
    )
  }
}
