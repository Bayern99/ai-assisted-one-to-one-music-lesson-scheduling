import SwiftUI

struct ContentView: View {
    @ObservedObject var runtime: ShellRuntime

    var body: some View {
        Group {
            switch runtime.state {
            case .idle, .starting:
                StartupView()
            case let .ready(url):
                DashboardWebView(applicationURL: url)
            case let .failed(message):
                FailureView(message: message, logFile: runtime.logFile) {
                    runtime.retry()
                }
            case .stopped:
                StartupView(label: "Stopping local workspace")
            }
        }
        .frame(minWidth: 1180, minHeight: 720)
        .ignoresSafeArea(.container, edges: .top)
        .task {
            await NativeTitlebarDragRegion.installWhenWindowAvailable()
        }
    }
}

private struct StartupView: View {
    var label = "Starting local scheduling workspace"

    var body: some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.small)
            Text(label)
                .font(.system(size: 13, weight: .medium))
            Text("Local scheduling workspace")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
    }
}

private struct FailureView: View {
    let message: String
    let logFile: URL?
    let retry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("AI-Assisted One-to-One Music Lesson Scheduling could not start")
                .font(.system(size: 24, weight: .semibold))
            Text(message)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            if let logFile {
                Text(logFile.path)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .textSelection(.enabled)
            }
            HStack {
                Button("Try Again", action: retry)
                    .keyboardShortcut(.defaultAction)
                if let logFile {
                    Button("Show Log") {
                        NSWorkspace.shared.activateFileViewerSelecting([logFile])
                    }
                }
            }
        }
        .padding(48)
        .frame(maxWidth: 720, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
    }
}
