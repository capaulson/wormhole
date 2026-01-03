import SwiftUI

/// Minimal home screen - session list with machines accessible via toolbar
struct HomeView: View {
    @Environment(AppState.self) private var appState
    @State private var showingMachines = false

    var body: some View {
        NavigationStack {
            SessionListView()
                .navigationTitle("Sessions")
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            showingMachines = true
                        } label: {
                            Image(systemName: "server.rack")
                        }
                    }

                    ToolbarItem(placement: .status) {
                        ConnectionStatusView()
                    }
                }
                .sheet(isPresented: $showingMachines) {
                    MachinesSheet()
                }
        }
    }
}

/// Shows connection status in toolbar
struct ConnectionStatusView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(appState.hasAnyConnection ? .green : .gray)
                .frame(width: 8, height: 8)
            Text(appState.connectionSummary)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

#Preview {
    HomeView()
        .environment(AppState())
}
