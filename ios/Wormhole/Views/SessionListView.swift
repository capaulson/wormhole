import SwiftUI

struct SessionListView: View {
    @Environment(AppState.self) private var appState
    let machineName: String

    var body: some View {
        List {
            if appState.sessions.isEmpty {
                ContentUnavailableView(
                    "No Sessions",
                    systemImage: "terminal",
                    description: Text("No Claude Code sessions are active on \(machineName)")
                )
                .listRowBackground(Color.clear)
            } else {
                ForEach(appState.sessions) { session in
                    NavigationLink(value: session.id) {
                        SessionRowView(session: session)
                    }
                }
            }
        }
        .navigationTitle(machineName)
        .navigationDestination(for: String.self) { sessionId in
            if let session = appState.sessions.first(where: { $0.id == sessionId }) {
                SessionDetailView(session: session)
            }
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Disconnect") {
                    appState.disconnect()
                }
            }
        }
        .overlay(alignment: .bottom) {
            if let error = appState.connectionError {
                ConnectionErrorBanner(error: error)
            }
        }
    }
}

struct ConnectionErrorBanner: View {
    let error: String

    var body: some View {
        Text(error)
            .font(.caption)
            .foregroundStyle(.white)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.red, in: Capsule())
            .padding()
    }
}

#Preview {
    NavigationStack {
        SessionListView(machineName: "My Mac")
    }
    .environment(AppState())
}
