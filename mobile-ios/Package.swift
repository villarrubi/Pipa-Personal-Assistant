// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "PipaMobileCore",
    platforms: [
        .iOS(.v16),
        // macOS is included so CryptoKit/Network/Keychain can be compiled and
        // tested in CI; the production client remains an iOS application.
        .macOS(.v13),
    ],
    products: [
        .library(
            name: "PipaMobileCore",
            targets: ["PipaMobileCore"]
        ),
        .library(
            name: "PipaMobileUI",
            targets: ["PipaMobileUI"]
        ),
    ],
    targets: [
        .target(name: "PipaMobileCore"),
        .target(
            name: "PipaMobileUI",
            dependencies: ["PipaMobileCore"]
        ),
        .testTarget(
            name: "PipaMobileCoreTests",
            dependencies: ["PipaMobileCore"]
        ),
        .testTarget(
            name: "PipaMobileUITests",
            dependencies: ["PipaMobileUI"]
        ),
    ]
)
