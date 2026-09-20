import AppKit
import SwiftUI

extension Notification.Name {
    static let interfaceTextSizeCommand = Notification.Name("pi.interfaceTextSizeCommand")
}

@main
struct MusicLessonSchedulerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("AI-Assisted One-to-One Music Lesson Scheduling", id: "dashboard") {
            ContentView(runtime: appDelegate.runtime)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1440, height: 900)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) { }
            CommandGroup(after: .appInfo) {
                Divider()
                Button("Reload Workspace") {
                    appDelegate.runtime.retry()
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
            }
            CommandGroup(after: .toolbar) {
                Divider()
                Button("Increase Text Size") {
                    NotificationCenter.default.post(name: .interfaceTextSizeCommand, object: "increase")
                }
                .keyboardShortcut("+", modifiers: .command)
                Button("Decrease Text Size") {
                    NotificationCenter.default.post(name: .interfaceTextSizeCommand, object: "decrease")
                }
                .keyboardShortcut("-", modifiers: .command)
                Button("Actual Text Size") {
                    NotificationCenter.default.post(name: .interfaceTextSizeCommand, object: "reset")
                }
                .keyboardShortcut("0", modifiers: .command)
            }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let runtime = ShellRuntime()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        runtime.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        runtime.stop()
    }
}
