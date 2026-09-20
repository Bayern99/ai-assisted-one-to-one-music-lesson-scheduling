import Foundation

public struct DesktopSessionSpec: Equatable, Sendable {
    public let contentURL: URL
    public let token: String

    public init?(applicationURL: URL) {
        guard
            applicationURL.scheme == "http",
            applicationURL.host == "127.0.0.1",
            applicationURL.port != nil,
            var components = URLComponents(
                url: applicationURL,
                resolvingAgainstBaseURL: false
            ),
            let token = components.queryItems?
                .first(where: { $0.name == "bootstrap" })?
                .value,
            !token.isEmpty
        else { return nil }

        let remainingItems = components.queryItems?.filter { $0.name != "bootstrap" } ?? []
        components.queryItems = remainingItems.isEmpty ? nil : remainingItems
        guard let contentURL = components.url else { return nil }

        self.contentURL = contentURL
        self.token = token
    }
}
