import PipaMobileUI
import SwiftUI

// Add this file to a new iOS App target in Xcode. It intentionally lives
// outside the Swift package targets so the package remains reusable and CI can
// test the core/UI libraries independently.
@main
struct PipaMobileApp: App {
    var body: some Scene {
        WindowGroup {
            PipaMobileRootView()
        }
    }
}
