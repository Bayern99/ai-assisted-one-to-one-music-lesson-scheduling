import AppKit
import DashboardShellCore
import Foundation

@MainActor
final class ArtifactSaveService {
    private let baseURL: URL
    private let token: String
    private var savedDestinations: [String: URL] = [:]

    init(applicationURL: URL) {
        guard let session = DesktopSessionSpec(applicationURL: applicationURL) else {
            preconditionFailure("The artifact service requires a loopback desktop session")
        }
        var components = URLComponents(
            url: session.contentURL,
            resolvingAgainstBaseURL: false
        )!
        token = session.token
        components.query = nil
        components.path = "/"
        baseURL = components.url!
    }

    func save(artifactID: String) async throws -> [String: Any] {
        let (data, filename) = try await fetch(artifactID: artifactID)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else {
            return ["saved": false, "filename": filename]
        }
        try data.write(to: destination, options: .atomic)
        savedDestinations[artifactID] = destination
        return [
            "saved": true,
            "filename": destination.lastPathComponent,
            "location": destination.deletingLastPathComponent().path,
        ]
    }

    func reveal(artifactID: String) throws -> [String: Any] {
        guard let destination = savedDestinations[artifactID] else {
            throw ArtifactSaveError.notSaved
        }
        NSWorkspace.shared.activateFileViewerSelecting([destination])
        return ["revealed": true]
    }

    private func fetch(artifactID: String) async throws -> (Data, String) {
        let candidates = try ArtifactContract.candidateURLs(
            baseURL: baseURL,
            artifactID: artifactID
        )
        for (index, url) in candidates.enumerated() {
            var request = URLRequest(url: url)
            request.setValue("pi_session=\(token)", forHTTPHeaderField: "Cookie")
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw ArtifactSaveError.invalidResponse
            }
            if http.statusCode == 404, index < candidates.count - 1 {
                continue
            }
            guard (200..<300).contains(http.statusCode) else {
                throw ArtifactSaveError.http(http.statusCode)
            }
            return (
                data,
                ArtifactContract.safeFilename(
                    from: http.value(forHTTPHeaderField: "Content-Disposition")
                )
            )
        }
        throw ArtifactSaveError.missing
    }
}

private enum ArtifactSaveError: LocalizedError {
    case invalidResponse
    case http(Int)
    case missing
    case notSaved

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "The local API returned an invalid artifact response."
        case let .http(status):
            return "Artifact download failed with HTTP \(status)."
        case .missing:
            return "The artifact is no longer available."
        case .notSaved:
            return "Save this artifact before revealing it in Finder."
        }
    }
}
