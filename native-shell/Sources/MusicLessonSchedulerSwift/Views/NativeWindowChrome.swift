import AppKit
import DashboardShellCore

@MainActor
enum NativeTitlebarDragRegion {
    static let identifier = NSUserInterfaceItemIdentifier(
        "edu.research.music-lesson-scheduler.native-titlebar-drag-region"
    )

    static func installWhenWindowAvailable() async {
        for _ in 0..<80 {
            if let window = NSApp.keyWindow ?? NSApp.windows.first {
                install(in: window)
                return
            }
            try? await Task.sleep(for: .milliseconds(25))
        }
    }

    static func install(in window: NSWindow) {
        if window.titlebarAccessoryViewControllers.contains(where: { $0.view.identifier == identifier }) {
            return
        }

        let contract = DesktopWindowChromeContract.standard
        window.styleMask.insert(.fullSizeContentView)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.toolbar = nil

        let dragView = NativeTitlebarDragRegionView(
            frame: NSRect(
                x: 0,
                y: 0,
                width: max(1, window.frame.width - CGFloat(contract.trafficLightExclusionWidth)),
                height: CGFloat(contract.dragRegionHeight)
            )
        )
        dragView.identifier = identifier
        dragView.autoresizingMask = [.width]
        dragView.setAccessibilityElement(false)

        let accessory = NSTitlebarAccessoryViewController()
        accessory.layoutAttribute = .left
        accessory.view = dragView
        window.addTitlebarAccessoryViewController(accessory)
    }
}

final class NativeTitlebarDragRegionView: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeKey()
        window?.performDrag(with: event)
    }
}
