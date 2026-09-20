import Combine
import DashboardShellCore
import Darwin
import Foundation

enum ShellRuntimeState: Equatable {
    case idle
    case starting
    case ready(URL)
    case failed(String)
    case stopped
}

@MainActor
final class ShellRuntime: ObservableObject {
    @Published private(set) var state: ShellRuntimeState = .idle
    @Published private(set) var logFile: URL?

    private var backendProcess: Process?
    private var logHandle: FileHandle?
    private var paths: ApplicationPaths?
    private var stopping = false
    private var startupTask: Task<Void, Never>?

    func start() {
        guard backendProcess == nil, startupTask == nil else { return }
        stopping = false
        state = .starting
        startupTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await self.startBackend()
            } catch is CancellationError {
                self.state = .stopped
            } catch {
                self.stopBackend()
                self.state = .failed(error.localizedDescription)
            }
            self.startupTask = nil
        }
    }

    func retry() {
        stopBackend()
        state = .idle
        start()
    }

    func stop() {
        stopping = true
        startupTask?.cancel()
        startupTask = nil
        stopBackend()
        state = .stopped
    }

    private func startBackend() async throws {
        let paths = try ApplicationPaths.load()
        self.paths = paths
        logFile = paths.logFile
        let token = Self.makeToken()
        let port = try LoopbackPort.available()
        let spec = BackendLaunchSpec.make(
            pythonExecutable: paths.pythonExecutable,
            piExecutable: paths.piExecutable,
            projectRoot: paths.projectRoot,
            dataDirectory: paths.dataDirectory,
            // Never start Python inside Documents. On File Provider-backed
            // folders Python's startup getcwd() can block before uvicorn runs.
            // PI_DATA_DIR remains the absolute source of truth for app data.
            workingDirectory: FileManager.default.temporaryDirectory,
            port: port,
            token: token,
            baseEnvironment: ProcessInfo.processInfo.environment
        )

        FileManager.default.createFile(atPath: paths.logFile.path, contents: nil)
        let logHandle = try FileHandle(forWritingTo: paths.logFile)
        try logHandle.seekToEnd()
        self.logHandle = logHandle

        let process = Process()
        process.executableURL = spec.executableURL
        process.arguments = spec.arguments
        process.currentDirectoryURL = spec.currentDirectoryURL
        process.environment = spec.environment
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self] terminated in
            Task { @MainActor [weak self] in
                guard
                    let self,
                    !self.stopping,
                    self.backendProcess === terminated
                else { return }
                self.backendProcess = nil
                self.cleanupRuntimeArtifacts()
                self.state = .failed(
                    "The local scheduling service stopped unexpectedly (exit \(terminated.terminationStatus))."
                )
            }
        }
        try process.run()
        backendProcess = process
        try writeRuntimeFile(paths: paths, port: port, backendPID: process.processIdentifier)
        try await waitUntilBackendReady(port: port, process: process)
        try Task.checkCancellation()
        state = .ready(spec.applicationURL)
    }

    private func waitUntilBackendReady(
        port: UInt16,
        process: Process
    ) async throws {
        let deadline = Date().addingTimeInterval(30)
        let url = URL(string: "http://127.0.0.1:\(port)/api/health")!
        while Date() < deadline {
            try Task.checkCancellation()
            guard process.isRunning else {
                throw RuntimeError.backendExited(process.terminationStatus)
            }
            do {
                let (_, response) = try await URLSession.shared.data(from: url)
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    return
                }
            } catch {
                if !process.isRunning {
                    throw RuntimeError.backendExited(process.terminationStatus)
                }
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw RuntimeError.startupTimedOut
    }

    private func stopBackend() {
        guard let process = backendProcess else {
            cleanupRuntimeArtifacts()
            return
        }
        backendProcess = nil
        if process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(3)
            while process.isRunning, Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
            }
            if process.isRunning {
                Darwin.kill(process.processIdentifier, SIGKILL)
            }
        }
        cleanupRuntimeArtifacts()
    }

    private func cleanupRuntimeArtifacts() {
        try? logHandle?.close()
        logHandle = nil
        if let runtimeFile = paths?.runtimeFile {
            try? FileManager.default.removeItem(at: runtimeFile)
        }
    }

    private func writeRuntimeFile(
        paths: ApplicationPaths,
        port: UInt16,
        backendPID: Int32
    ) throws {
        let payload: [String: Any] = [
            "shell_pid": ProcessInfo.processInfo.processIdentifier,
            "backend_pid": backendPID,
            "port": port,
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        try data.write(to: paths.runtimeFile, options: .atomic)
    }

    private static func makeToken() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "")
            + UUID().uuidString.replacingOccurrences(of: "-", with: "")
    }
}

private enum RuntimeError: LocalizedError {
    case backendExited(Int32)
    case startupTimedOut

    var errorDescription: String? {
        switch self {
        case let .backendExited(status):
            return "The local scheduling service exited during startup (exit \(status))."
        case .startupTimedOut:
            return "The local scheduling service did not become ready within 30 seconds."
        }
    }
}
