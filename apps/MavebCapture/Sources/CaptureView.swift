import ARKit
import RealityKit
import SwiftUI

struct ARPreview: UIViewRepresentable {
  let session: ARSession

  func makeUIView(context: Context) -> ARView {
    let view = ARView(frame: .zero)
    view.automaticallyConfigureSession = false
    view.session = session
    view.environment.sceneUnderstanding.options = [.occlusion, .physics]
    view.debugOptions = [.showSceneUnderstanding]
    return view
  }

  func updateUIView(_ uiView: ARView, context: Context) {}
}

private struct CaptureMetric: View {
  let value: String
  let label: String
  let symbol: String
  var warning = false

  var body: some View {
    VStack(alignment: .leading, spacing: 3) {
      Label(label, systemImage: symbol)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
      Text(value)
        .font(.subheadline.monospacedDigit().weight(.semibold))
        .foregroundStyle(warning ? .orange : .primary)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

struct CaptureView: View {
  @StateObject private var controller = CaptureController()

  var body: some View {
    ZStack {
      ARPreview(session: controller.session)
        .ignoresSafeArea()

      LinearGradient(
        colors: [.black.opacity(0.42), .clear, .black.opacity(0.58)],
        startPoint: .top,
        endPoint: .bottom
      )
      .ignoresSafeArea()
      .allowsHitTesting(false)

      VStack(spacing: 0) {
        topBar
        Spacer()
        captureCard
      }
      .padding(16)
    }
    .onAppear { controller.startSession() }
  }

  private var topBar: some View {
    HStack(spacing: 10) {
      HStack(spacing: 8) {
        Image(systemName: "hexagon.fill")
          .foregroundStyle(.white)
        VStack(alignment: .leading, spacing: 0) {
          Text("MAVEB CAPTURE")
            .font(.caption.weight(.bold))
            .tracking(1.1)
          Text("METRIC RGB-D")
            .font(.caption2.weight(.medium))
            .foregroundStyle(.white.opacity(0.68))
        }
      }

      Spacer()

      HStack(spacing: 7) {
        Circle()
          .fill(controller.trackingState == "Normal" ? Color.green : Color.orange)
          .frame(width: 7, height: 7)
        Text(controller.trackingState)
          .font(.caption.weight(.semibold))
      }
    }
    .foregroundStyle(.white)
    .padding(.horizontal, 14)
    .padding(.vertical, 11)
    .background(.ultraThinMaterial, in: Capsule())
  }

  private var captureCard: some View {
    VStack(spacing: 14) {
      HStack(spacing: 12) {
        CaptureMetric(
          value: controller.status.acceptedFrames.formatted(),
          label: "CAPTURED",
          symbol: "camera.fill"
        )
        CaptureMetric(
          value: controller.status.droppedFrames.formatted(),
          label: "DROPPED",
          symbol: "arrow.down.circle",
          warning: controller.status.droppedFrames > 0
        )
        CaptureMetric(
          value: controller.status.rejectedFrames.formatted(),
          label: "FILTERED",
          symbol: "line.3.horizontal.decrease.circle",
          warning: controller.status.rejectedFrames > 0
        )
      }

      Divider()

      if let error = controller.lastError {
        Label(error, systemImage: "exclamationmark.triangle.fill")
          .font(.footnote)
          .foregroundStyle(.red)
          .frame(maxWidth: .infinity, alignment: .leading)
          .padding(10)
          .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
      }

      HStack(spacing: 12) {
        Button {
          controller.status.recording
            ? controller.stopRecording()
            : controller.startRecording()
        } label: {
          HStack(spacing: 9) {
            Image(systemName: controller.status.recording ? "stop.fill" : "record.circle")
            Text(controller.status.recording ? "Stop & Save" : "Start RGB-D Scan")
              .fontWeight(.semibold)
          }
          .frame(maxWidth: .infinity)
          .padding(.vertical, 5)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .tint(controller.status.recording ? .red : .blue)

        if let package = controller.status.packageURL, !controller.status.recording {
          ShareLink(item: package) {
            Label("Export", systemImage: "square.and.arrow.up")
              .padding(.vertical, 5)
          }
          .buttonStyle(.bordered)
          .controlSize(.large)
        }
      }

      HStack(spacing: 7) {
        if controller.status.recording {
          Circle()
            .fill(.red)
            .frame(width: 7, height: 7)
        }
        Text(controller.status.message)
          .font(.caption)
          .foregroundStyle(.secondary)
          .frame(maxWidth: .infinity, alignment: .leading)
      }
    }
    .padding(16)
    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    .overlay {
      RoundedRectangle(cornerRadius: 22, style: .continuous)
        .stroke(Color.white.opacity(0.14), lineWidth: 1)
    }
  }
}
