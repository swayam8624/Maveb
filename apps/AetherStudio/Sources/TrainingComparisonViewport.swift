import SwiftUI

struct TrainingComparisonViewport: NSViewRepresentable {
    let scenePath: String
    @Binding var camera: AetherCameraState

    final class Coordinator {
        var scenePath = ""
        var camera = AetherCameraState()
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> AetherViewportView {
        let view = AetherViewportView(frame: .zero)
        view.preferredFramesPerSecond = 30
        view.scenePath = scenePath
        view.cameraState = camera.values.map { NSNumber(value: $0) }
        view.gaussianDebugMode = 0
        view.exposureStops = 0
        view.onCameraChanged = cameraCallback
        context.coordinator.scenePath = scenePath
        context.coordinator.camera = camera
        return view
    }

    func updateNSView(_ view: AetherViewportView, context: Context) {
        view.onCameraChanged = cameraCallback
        if context.coordinator.scenePath != scenePath {
            view.scenePath = scenePath
            context.coordinator.scenePath = scenePath
        }
        if context.coordinator.camera != camera {
            view.cameraState = camera.values.map { NSNumber(value: $0) }
            context.coordinator.camera = camera
        }
    }

    private var cameraCallback: ([NSNumber]) -> Void {
        { values in
            guard values.count == 6 else { return }
            camera = AetherCameraState(positionX: values[0].floatValue,
                                       positionY: values[1].floatValue,
                                       positionZ: values[2].floatValue,
                                       yaw: values[3].floatValue,
                                       pitch: values[4].floatValue,
                                       verticalFieldOfViewRadians: values[5].floatValue)
        }
    }
}
