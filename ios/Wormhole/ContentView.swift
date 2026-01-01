import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        NavigationStack {
            if appState.isConnected, let machine = appState.selectedMachine {
                SessionListView(machineName: machine.name)
            } else {
                MachineListView()
            }
        }
    }
}

#Preview {
    ContentView()
        .environment(AppState())
}
