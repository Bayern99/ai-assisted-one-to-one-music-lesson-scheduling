import AppKit
import Testing
@testable import MusicLessonSchedulerSwift

@Test @MainActor
func titlebarDragRegionInstallsOnceInTheNativeTitlebarLayer() {
    let window = NSWindow(
        contentRect: NSRect(x: 0, y: 0, width: 1180, height: 720),
        styleMask: [.titled, .closable, .resizable],
        backing: .buffered,
        defer: false
    )

    NativeTitlebarDragRegion.install(in: window)
    NativeTitlebarDragRegion.install(in: window)

    let regions = window.titlebarAccessoryViewControllers.filter {
        $0.view.identifier == NativeTitlebarDragRegion.identifier
    }
    #expect(regions.count == 1)
    #expect(regions.first?.layoutAttribute == .left)
    #expect(regions.first?.view is NativeTitlebarDragRegionView)
    #expect(window.styleMask.contains(.fullSizeContentView))
    #expect(window.titleVisibility == .hidden)
    #expect(window.titlebarAppearsTransparent)
}
