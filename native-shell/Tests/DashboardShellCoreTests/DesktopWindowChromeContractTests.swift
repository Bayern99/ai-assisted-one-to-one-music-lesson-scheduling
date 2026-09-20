import Testing
@testable import DashboardShellCore

@Test func desktopWindowChromeKeepsNativeBehaviorWithoutVisibleTitleFurniture() {
    let contract = DesktopWindowChromeContract.standard

    #expect(contract.usesFullSizeContentView)
    #expect(contract.hidesVisibleTitle)
    #expect(contract.usesTransparentTitlebar)
    #expect(contract.removesToolbar)
    #expect(contract.removesTitlebarSeparator)
    #expect(contract.extendsContentThroughTitlebarSafeArea)
    #expect(contract.preservesNativeWindowButtons)
    #expect(contract.preservesResizeAndFullScreen)
    #expect(contract.preservesStateRestoration)
}

@Test func desktopWindowChromeReservesTrafficLightsAndASeparateDragBand() {
    let contract = DesktopWindowChromeContract.standard

    #expect(contract.titlebarInset == 28)
    #expect(contract.dragRegionHeight == 28)
    #expect(contract.trafficLightExclusionWidth == 78)
    #expect(contract.dragRegionHeight <= contract.titlebarInset)
}
