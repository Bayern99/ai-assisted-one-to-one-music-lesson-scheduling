public struct DesktopWindowChromeContract: Equatable, Sendable {
    public let usesFullSizeContentView: Bool
    public let hidesVisibleTitle: Bool
    public let usesTransparentTitlebar: Bool
    public let removesToolbar: Bool
    public let removesTitlebarSeparator: Bool
    public let extendsContentThroughTitlebarSafeArea: Bool
    public let preservesNativeWindowButtons: Bool
    public let preservesResizeAndFullScreen: Bool
    public let preservesStateRestoration: Bool
    public let titlebarInset: Int
    public let dragRegionHeight: Int
    public let trafficLightExclusionWidth: Int

    public static let standard = DesktopWindowChromeContract(
        usesFullSizeContentView: true,
        hidesVisibleTitle: true,
        usesTransparentTitlebar: true,
        removesToolbar: true,
        removesTitlebarSeparator: true,
        extendsContentThroughTitlebarSafeArea: true,
        preservesNativeWindowButtons: true,
        preservesResizeAndFullScreen: true,
        preservesStateRestoration: true,
        titlebarInset: 28,
        dragRegionHeight: 28,
        trafficLightExclusionWidth: 78
    )

}
