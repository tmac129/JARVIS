// swift-tools-version:5.10
import PackageDescription

let regex: [SwiftSetting] = [.enableUpcomingFeature("BareSlashRegexLiterals")]

let package = Package(
    name: "JARVIS",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "jarvis", targets: ["jarvis"]),
        .executable(name: "JarvisHUD", targets: ["JarvisHUD"]),
        .library(name: "JarvisCore", targets: ["JarvisCore"]),
    ],
    targets: [
        .target(name: "JarvisCore", swiftSettings: regex, linkerSettings: [.linkedFramework("EventKit"), .linkedFramework("PDFKit"), .linkedFramework("AppKit"), .linkedLibrary("sqlite3")]),
        .executableTarget(name: "jarvis", dependencies: ["JarvisCore"], swiftSettings: regex),
        .executableTarget(
            name: "JarvisHUD", dependencies: ["JarvisCore"], path: "Sources/JarvisApp", swiftSettings: regex,
            linkerSettings: [.linkedFramework("AppKit"), .linkedFramework("WebKit"), .linkedFramework("IOKit"), .linkedFramework("Carbon")]
        ),
    ]
)
