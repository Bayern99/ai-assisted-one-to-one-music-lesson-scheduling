import Foundation

public struct BackendLaunchSpec: Equatable, Sendable {
    public let executableURL: URL
    public let arguments: [String]
    public let currentDirectoryURL: URL
    public let environment: [String: String]
    public let applicationURL: URL

    public static func make(
        pythonExecutable: URL,
        piExecutable: URL?,
        projectRoot: URL,
        dataDirectory: URL,
        workingDirectory: URL,
        port: UInt16,
        token: String,
        baseEnvironment: [String: String]
    ) -> BackendLaunchSpec {
        var environment = baseEnvironment
        environment.removeValue(forKey: "PYTHONHOME")
        environment.removeValue(forKey: "PYTHONPATH")
        environment.removeValue(forKey: "PYTHONNOUSERSITE")
        environment.removeValue(forKey: "PI_EXECUTABLE")
        environment["PI_BOOTSTRAP_TOKEN"] = token
        environment["PI_DATA_DIR"] = dataDirectory.path
        if let piExecutable {
            environment["PI_EXECUTABLE"] = piExecutable.path
        }

        let arguments = [
            "-m", "uvicorn",
            "--app-dir", projectRoot.path,
            "modules.api.runtime:app",
            "--no-access-log",
            "--host", "127.0.0.1",
            "--port", String(port),
        ]
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = Int(port)
        components.path = "/"
        components.queryItems = [URLQueryItem(name: "bootstrap", value: token)]

        return BackendLaunchSpec(
            executableURL: pythonExecutable,
            arguments: arguments,
            currentDirectoryURL: workingDirectory,
            environment: environment,
            applicationURL: components.url!
        )
    }
}
