public enum DesktopBridgeContract {
    public static let bridgeScript = """
    document.documentElement.dataset.piDesktop = 'macos';
    window.piDesktop = window.piDesktop || {};
    window.piDesktop.saveArtifact = function (artifactId) {
      return window.webkit.messageHandlers.piDesktop.postMessage({
        action: 'saveArtifact',
        artifactId: artifactId
      });
    };
    window.piDesktop.openFile = function (kind) {
      return window.webkit.messageHandlers.piDesktop.postMessage({
        action: 'openFile',
        kind: kind
      });
    };
    window.piDesktop.revealArtifact = function (artifactId) {
      return window.webkit.messageHandlers.piDesktop.postMessage({
        action: 'revealArtifact',
        artifactId: artifactId
      });
    };
    """
}
