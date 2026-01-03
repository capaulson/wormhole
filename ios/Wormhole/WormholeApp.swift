import SwiftUI

@main
@MainActor
struct WormholeApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .task {
                    appState.startDiscovery()
                }
        }
    }
}
