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

struct CaptureView: View {
  @StateObject private var controller = CaptureController()

  var body: some View {
    ZStack(alignment: .bottom) {
      ARPreview(session: controller.session)
        .ignoresSafeArea()

      VStack(spacing: 12) {
        HStack {
          Label(
            controller.trackingState,
            systemImage: controller.trackingState == "Normal"
              ? "location.fill" : "location.slash")
          Spacer()
          Text("\(controller.status.acceptedFrames) frames")
          if controller.status.droppedFrames > 0 {
            Text("\(controller.status.droppedFrames) dropped")
              .foregroundStyle(.orange)
          }
          if controller.status.rejectedFrames > 0 {
            Text("\(controller.status.rejectedFrames) filtered")
              .foregroundStyle(.secondary)
          }
        }
        .font(.subheadline.monospacedDigit())

        if let error = controller.lastError {
          Text(error)
            .font(.footnote)
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading)
        }

        HStack(spacing: 16) {
          Button {
            controller.status.recording
              ? controller.stopRecording()
              : controller.startRecording()
          } label: {
            Label(
              controller.status.recording ? "Stop and Save" : "Start RGB-D Scan",
              systemImage: controller.status.recording
                ? "stop.circle.fill" : "record.circle"
            )
            .frame(maxWidth: .infinity)
          }
          .buttonStyle(.borderedProminent)
          .tint(controller.status.recording ? .red : .blue)

          if let package = controller.status.packageURL,
            !controller.status.recording
          {
            ShareLink(item: package) {
              Label("Export", systemImage: "square.and.arrow.up")
            }
            .buttonStyle(.bordered)
          }
        }

        Text(controller.status.message)
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .padding()
      .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
      .padding()
    }
    .onAppear { controller.startSession() }
  }
}
