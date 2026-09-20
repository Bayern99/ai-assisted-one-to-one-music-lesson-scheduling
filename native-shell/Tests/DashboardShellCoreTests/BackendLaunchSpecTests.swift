import Foundation
import Testing
@testable import DashboardShellCore

@Test func launchSpecUsesLoopbackAndKeepsTokenOutOfArguments() throws {
    let spec = BackendLaunchSpec.make(
        pythonExecutable: URL(fileURLWithPath: "/opt/homebrew/bin/python3"),
        piExecutable: URL(fileURLWithPath: "/opt/homebrew/bin/pi"),
        projectRoot: URL(fileURLWithPath: "/tmp/music-lesson-scheduler"),
        dataDirectory: URL(fileURLWithPath: "/tmp/music-lesson-scheduler-data"),
        workingDirectory: URL(fileURLWithPath: "/tmp"),
        port: 8765,
        token: "a+/= secret",
        baseEnvironment: [
            "PATH": "/usr/bin",
            "PYTHONHOME": "/unsafe/home",
            "PYTHONPATH": "/unsafe/path",
            "PYTHONNOUSERSITE": "1",
        ]
    )

    #expect(spec.arguments.suffix(4) == ["--host", "127.0.0.1", "--port", "8765"])
    #expect(spec.arguments.prefix(4) == ["-m", "uvicorn", "--app-dir", "/tmp/music-lesson-scheduler"])
    #expect(!spec.arguments.contains(where: { $0.contains("secret") }))
    #expect(spec.currentDirectoryURL.path == "/tmp")
    #expect(spec.applicationURL.absoluteString == "http://127.0.0.1:8765/?bootstrap=a+/%3D%20secret")
    #expect(spec.environment["PI_BOOTSTRAP_TOKEN"] == "a+/= secret")
    #expect(spec.environment["PI_DATA_DIR"] == "/tmp/music-lesson-scheduler-data")
    #expect(spec.environment["PI_EXECUTABLE"] == "/opt/homebrew/bin/pi")
    #expect(spec.environment["PATH"] == "/usr/bin")
    #expect(spec.environment["PYTHONHOME"] == nil)
    #expect(spec.environment["PYTHONPATH"] == nil)
    #expect(spec.environment["PYTHONNOUSERSITE"] == nil)
}
