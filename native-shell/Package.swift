// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "MusicLessonSchedulerNativeShell",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "DashboardShellCore", targets: ["DashboardShellCore"]),
        .executable(name: "MusicLessonSchedulerSwift", targets: ["MusicLessonSchedulerSwift"]),
    ],
    targets: [
        .target(name: "DashboardShellCore"),
        .executableTarget(
            name: "MusicLessonSchedulerSwift",
            dependencies: ["DashboardShellCore"]
        ),
        .testTarget(
            name: "DashboardShellCoreTests",
            dependencies: ["DashboardShellCore"]
        ),
        .testTarget(
            name: "MusicLessonSchedulerSwiftTests",
            dependencies: ["MusicLessonSchedulerSwift"]
        ),
    ]
)
