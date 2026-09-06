import AppKit
import SwiftUI

@main
struct AetherStudioApp: App {
    var body: some Scene {
        DocumentGroup(newDocument: AetherProjectDocument()) { file in
            ContentView(document: file.$document, projectURL: file.fileURL)
                .frame(minWidth: 1180, minHeight: 720)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified(showsTitle: false))

        Settings {
            AetherSettingsView()
        }
    }
}

private struct AetherSettingsView: View {
    @AppStorage("preferredFramesPerSecond") private var preferredFramesPerSecond = 60
    @AppStorage("showRendererDiagnostics") private var showRendererDiagnostics = false
    @State private var exportError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 9) {
                    Image(systemName: "hexagon.fill")
                        .foregroundStyle(Color.accentColor)
                    Text("AETHER Settings")
                        .font(.title3.weight(.semibold))
                }
                Text("Viewport performance and local diagnostics.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            GroupBox("Viewport") {
                Form {
                    Picker("Frame rate", selection: $preferredFramesPerSecond) {
                        Text("30 fps").tag(30)
                        Text("60 fps").tag(60)
                        Text("120 fps").tag(120)
                    }
                    Toggle("Show renderer diagnostics", isOn: $showRendererDiagnostics)
                }
                .formStyle(.grouped)
            }

            GroupBox("Diagnostics") {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        LabeledContent("Version", value: "0.1.0")
                        Spacer()
                    }
                    Text("Exports the local renderer diagnostics bundle without uploading project data.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Export Diagnostics…", systemImage: "square.and.arrow.up") {
                        exportDiagnostics()
                    }
                }
                .padding(6)
            }
        }
        .padding(20)
        .frame(width: 500)
        .alert("Diagnostics Export Failed", isPresented: Binding(
            get: { exportError != nil },
            set: { if !$0 { exportError = nil } }
        )) {
            Button("OK") { exportError = nil }
        } message: {
            Text(exportError ?? "Unknown error")
        }
    }

    private func exportDiagnostics() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "AetherDiagnostics.json"
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        var error: NSError?
        if !AetherWriteDiagnostics(url, &error) {
            exportError = error?.localizedDescription ?? "AETHER could not write the report."
        }
    }
}
