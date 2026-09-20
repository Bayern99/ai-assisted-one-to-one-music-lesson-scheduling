import AppKit
import DashboardShellCore
import SwiftUI
import WebKit

struct DashboardWebView: NSViewRepresentable {
    let applicationURL: URL

    func makeCoordinator() -> Coordinator {
        Coordinator(applicationURL: applicationURL)
    }

    func makeNSView(context: Context) -> WKWebView {
        let contentController = WKUserContentController()
        contentController.addScriptMessageHandler(
            context.coordinator.bridge,
            contentWorld: .page,
            name: "piDesktop"
        )
        let desktopBridgeScript = WKUserScript(
            source: DesktopBridgeContract.bridgeScript,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        contentController.addUserScript(desktopBridgeScript)

        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController
        // Use the app-scoped WebKit store so the HttpOnly session cookie set by
        // /api/auth/exchange is available to the workspace's API requests.
        configuration.websiteDataStore = .default()

        let webView = WKWebView(frame: .zero, configuration: configuration)
        context.coordinator.webView = webView
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = false
        webView.load(URLRequest(url: applicationURL))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.applicationURL = applicationURL
    }

    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: "piDesktop",
            contentWorld: .page
        )
        webView.navigationDelegate = nil
        coordinator.webView = nil
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        var applicationURL: URL
        let bridge: DesktopBridge
        weak var webView: WKWebView?

        init(applicationURL: URL) {
            self.applicationURL = applicationURL
            bridge = DesktopBridge(applicationURL: applicationURL)
            super.init()
            NotificationCenter.default.addObserver(
                self,
                selector: #selector(handleTextSizeCommand(_:)),
                name: .interfaceTextSizeCommand,
                object: nil
            )
        }

        deinit {
            NotificationCenter.default.removeObserver(self)
        }

        @objc private func handleTextSizeCommand(_ notification: Notification) {
            guard let command = notification.object as? String,
                  ["increase", "decrease", "reset"].contains(command)
            else { return }
            webView?.evaluateJavaScript(
                "window.dispatchEvent(new CustomEvent('pi:text-size', {detail:'\(command)'}))"
            )
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if url.host == "127.0.0.1", url.port == applicationURL.port {
                decisionHandler(.allow)
            } else if navigationAction.navigationType == .linkActivated {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.cancel)
            }
        }

    }
}

@MainActor
final class DesktopBridge: NSObject, WKScriptMessageHandlerWithReply {
    private let saveService: ArtifactSaveService
    private let openService = FileOpenService()

    init(applicationURL: URL) {
        saveService = ArtifactSaveService(applicationURL: applicationURL)
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) async -> (Any?, String?) {
        guard let body = message.body as? [String: Any], let action = body["action"] as? String else {
            return (nil, "Unsupported desktop bridge request")
        }
        do {
            switch action {
            case "openFile":
                guard let kind = body["kind"] as? String else {
                    return (nil, "A supported file kind is required")
                }
                return (try openService.choose(kind: kind), nil)
            case "saveArtifact":
                guard let artifactID = body["artifactId"] as? String else {
                    return (nil, "An artifact identifier is required")
                }
                return (try await saveService.save(artifactID: artifactID), nil)
            case "revealArtifact":
                guard let artifactID = body["artifactId"] as? String else {
                    return (nil, "An artifact identifier is required")
                }
                return (try saveService.reveal(artifactID: artifactID), nil)
            default:
                return (nil, "Unsupported desktop bridge request")
            }
        } catch {
            return (nil, error.localizedDescription)
        }
    }
}
