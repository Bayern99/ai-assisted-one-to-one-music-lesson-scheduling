import Foundation
import Testing
@testable import DashboardShellCore

@Test func desktopSessionExtractsTokenAndRemovesItFromVisibleURL() throws {
    let applicationURL = try #require(
        URL(string: "http://127.0.0.1:8765/?bootstrap=secret&view=week")
    )
    let session = try #require(DesktopSessionSpec(applicationURL: applicationURL))

    #expect(session.token == "secret")
    #expect(session.contentURL.absoluteString == "http://127.0.0.1:8765/?view=week")
}

@Test func desktopSessionRejectsMissingTokenAndNonLoopbackHosts() {
    #expect(DesktopSessionSpec(applicationURL: URL(string: "http://127.0.0.1:8765/")!) == nil)
    #expect(DesktopSessionSpec(applicationURL: URL(string: "https://example.com/?bootstrap=x")!) == nil)
}
