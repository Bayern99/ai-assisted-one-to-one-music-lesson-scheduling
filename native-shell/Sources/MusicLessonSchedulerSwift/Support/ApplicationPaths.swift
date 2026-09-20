import Foundation

enum ApplicationPathsError: LocalizedError {
    case missingResource(String)
    case missingProject(URL)
    case missingPython(URL)

    var errorDescription: String? {
        switch self {
        case let .missingResource(name):
            return "The app bundle is missing its \(name) configuration. Rebuild the Swift shell."
        case let .missingProject(url):
            return "The AI-Assisted One-to-One Music Lesson Scheduling project could not be found at \(url.path)."
        case let .missingPython(url):
            return "The local scheduling runtime could not be found at \(url.path). Reinstall the application."
        }
    }
}

struct ApplicationPaths: Sendable {
    let projectRoot: URL
    let pythonExecutable: URL
    let piExecutable: URL?
    let dataDirectory: URL
    let logFile: URL
    let runtimeFile: URL

    static func load(
        bundle: Bundle = .main,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> ApplicationPaths {
        let projectRoot = try runtimeProjectRoot(bundle: bundle, environment: environment)
        let pythonExecutable = try configuredURL(
            environmentKey: "PI_PYTHON_EXECUTABLE",
            resourceName: "python-executable",
            bundle: bundle,
            environment: environment
        )
        guard FileManager.default.fileExists(
            atPath: projectRoot.appending(path: "modules/api/runtime.py").path
        ) else {
            throw ApplicationPathsError.missingProject(projectRoot)
        }
        guard FileManager.default.isExecutableFile(atPath: pythonExecutable.path) else {
            throw ApplicationPathsError.missingPython(pythonExecutable)
        }
        let piExecutable = try? configuredURL(
            environmentKey: "PI_EXECUTABLE",
            resourceName: "pi-executable",
            bundle: bundle,
            environment: environment
        )

        let dataDirectory: URL
        if let configured = environment["PI_SWIFT_DATA_DIR"], !configured.isEmpty {
            dataDirectory = URL(fileURLWithPath: configured).standardizedFileURL
        } else if let configured = try? configuredURL(
            environmentKey: "PI_SWIFT_DATA_DIR",
            resourceName: "data-directory",
            bundle: bundle,
            environment: environment
        ) {
            dataDirectory = configured
        } else {
            dataDirectory = FileManager.default.homeDirectoryForCurrentUser
                .appending(path: "Library/Application Support/Music Lesson Scheduler/Data")
        }
        let logsDirectory = dataDirectory.appending(path: "logs")
        try FileManager.default.createDirectory(
            at: logsDirectory,
            withIntermediateDirectories: true
        )
        return ApplicationPaths(
            projectRoot: projectRoot,
            pythonExecutable: pythonExecutable,
            piExecutable: piExecutable.flatMap {
                FileManager.default.isExecutableFile(atPath: $0.path) ? $0 : nil
            },
            dataDirectory: dataDirectory,
            logFile: logsDirectory.appending(path: "swift-shell.log"),
            runtimeFile: logsDirectory.appending(path: "swift-shell-runtime.json")
        )
    }

    private static func runtimeProjectRoot(
        bundle: Bundle,
        environment: [String: String]
    ) throws -> URL {
        if let configured = environment["PI_PROJECT_DIR"], !configured.isEmpty {
            return URL(fileURLWithPath: configured).standardizedFileURL
        }
        if let resources = bundle.resourceURL {
            let bundledRuntime = resources.appending(path: "runtime")
            let bundledEntryPoint = bundledRuntime.appending(path: "modules/api/runtime.py")
            if FileManager.default.fileExists(atPath: bundledEntryPoint.path) {
                return bundledRuntime.standardizedFileURL
            }
        }
        return try configuredURL(
            environmentKey: "PI_PROJECT_DIR",
            resourceName: "project-root",
            bundle: bundle,
            environment: environment
        )
    }

    private static func configuredURL(
        environmentKey: String,
        resourceName: String,
        bundle: Bundle,
        environment: [String: String]
    ) throws -> URL {
        if let configured = environment[environmentKey], !configured.isEmpty {
            return URL(fileURLWithPath: configured).standardizedFileURL
        }
        guard let resource = bundle.url(forResource: resourceName, withExtension: nil) else {
            throw ApplicationPathsError.missingResource(resourceName)
        }
        let value = try String(contentsOf: resource, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            throw ApplicationPathsError.missingResource(resourceName)
        }
        return URL(fileURLWithPath: value).standardizedFileURL
    }
}
