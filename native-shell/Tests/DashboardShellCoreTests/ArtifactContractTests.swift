import Foundation
import Testing
@testable import DashboardShellCore

@Test func artifactContractUsesOnlyFixedLoopbackRoutes() throws {
    let urls = try ArtifactContract.candidateURLs(
        baseURL: URL(string: "http://127.0.0.1:8765")!,
        artifactID: "opaque_id-123"
    )

    #expect(urls.map(\.absoluteString) == [
        "http://127.0.0.1:8765/api/scheduler/exports/opaque_id-123",
        "http://127.0.0.1:8765/api/assessment/exports/opaque_id-123",
    ])
}

@Test(arguments: ["../secret", "https://evil.test/x", "a/b", "a.b", ""])
func artifactContractRejectsPathsAndURLs(_ artifactID: String) {
    #expect(throws: ArtifactContractError.invalidIdentifier) {
        try ArtifactContract.candidateURLs(
            baseURL: URL(string: "http://127.0.0.1:8765")!,
            artifactID: artifactID
        )
    }
}

@Test func artifactContractRejectsNonLoopbackBaseURL() {
    #expect(throws: ArtifactContractError.invalidBaseURL) {
        try ArtifactContract.candidateURLs(
            baseURL: URL(string: "https://example.com")!,
            artifactID: "opaque"
        )
    }
}

@Test func filenameIsReducedToItsLastSafePathComponent() {
    #expect(
        ArtifactContract.safeFilename(
            from: "attachment; filename=\"../../PI-Schedule.xlsx\""
        ) == "PI-Schedule.xlsx"
    )
    #expect(ArtifactContract.safeFilename(from: nil) == "Lesson-Scheduler-export.xlsx")
}
