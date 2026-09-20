import Foundation

public enum ArtifactContractError: LocalizedError, Equatable {
    case invalidIdentifier
    case invalidBaseURL

    public var errorDescription: String? {
        switch self {
        case .invalidIdentifier:
            return "Expected an opaque artifact id"
        case .invalidBaseURL:
            return "The local API URL is invalid"
        }
    }
}

public enum ArtifactContract {
    private static let routeTemplates = [
        "/api/scheduler/exports/",
        "/api/assessment/exports/",
    ]

    public static func candidateURLs(baseURL: URL, artifactID: String) throws -> [URL] {
        let validCharacters = CharacterSet.alphanumerics.union(
            CharacterSet(charactersIn: "_-")
        )
        guard
            !artifactID.isEmpty,
            artifactID.unicodeScalars.allSatisfy(validCharacters.contains)
        else {
            throw ArtifactContractError.invalidIdentifier
        }
        guard baseURL.scheme == "http", baseURL.host == "127.0.0.1" else {
            throw ArtifactContractError.invalidBaseURL
        }
        return try routeTemplates.map { route in
            guard let url = URL(string: route + artifactID, relativeTo: baseURL)?.absoluteURL else {
                throw ArtifactContractError.invalidBaseURL
            }
            return url
        }
    }

    public static func safeFilename(from contentDisposition: String?) -> String {
        guard
            let contentDisposition,
            let match = contentDisposition.firstMatch(
                of: /filename="?([^";]+)"?/
            )
        else {
            return "Lesson-Scheduler-export.xlsx"
        }
        let filename = URL(fileURLWithPath: String(match.1)).lastPathComponent
        return filename.isEmpty ? "Lesson-Scheduler-export.xlsx" : filename
    }
}
