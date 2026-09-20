import Testing
@testable import DashboardShellCore

@Test func desktopBridgeExposesNarrowDesktopFileCapabilities() {
    let source = DesktopBridgeContract.bridgeScript

    #expect(source.contains("document.documentElement.dataset.piDesktop = 'macos'"))
    #expect(source.contains("window.piDesktop.saveArtifact"))
    #expect(source.contains("action: 'saveArtifact'"))
    #expect(source.contains("artifactId: artifactId"))
    #expect(source.contains("window.piDesktop.openFile"))
    #expect(source.contains("action: 'openFile'"))
    #expect(source.contains("kind: kind"))
    #expect(source.contains("window.piDesktop.revealArtifact"))
    #expect(source.contains("action: 'revealArtifact'"))
    #expect(!source.contains("readFile"))
    #expect(!source.contains("writeFile"))
    #expect(!source.contains("execute"))
}
