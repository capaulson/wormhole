import SwiftUI

/// Lists all sessions from all connected machines
struct SessionListView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        List {
            if appState.allSessions.isEmpty {
                emptyStateView
                    .listRowBackground(Color.clear)
            } else {
                // Sessions needing attention first
                if !appState.sessionsNeedingAttention.isEmpty {
                    Section {
                        ForEach(appState.sessionsNeedingAttention) { session in
                            NavigationLink(value: session.id) {
                                SessionRowView(session: session)
                            }
                        }
                    } header: {
                        Label("Needs Attention", systemImage: "exclamationmark.circle.fill")
                            .foregroundStyle(.purple)
                    }
                }

                // All other sessions
                Section {
                    ForEach(otherSessions) { session in
                        NavigationLink(value: session.id) {
                            SessionRowView(session: session)
                        }
                    }
                } header: {
                    if !appState.sessionsNeedingAttention.isEmpty {
                        Text("All Sessions")
                    }
                }
            }
        }
        .navigationDestination(for: String.self) { sessionId in
            if let session = appState.session(byId: sessionId) {
                SessionDetailView(session: session)
            }
        }
        .overlay(alignment: .bottom) {
            if let error = appState.lastError {
                ConnectionErrorBanner(error: error)
            }
        }
    }

    private var emptyStateView: some View {
        Group {
            if appState.hasAnyConnection {
                ContentUnavailableView(
                    "No Sessions",
                    systemImage: "terminal",
                    description: Text("No Claude Code sessions are active.\nRun 'wormhole open --name <name>' to create one.")
                )
            } else if appState.machines.isEmpty {
                ContentUnavailableView(
                    "Searching...",
                    systemImage: "wifi",
                    description: Text("Looking for Wormhole daemons on your network")
                )
            } else {
                ContentUnavailableView(
                    "Connecting...",
                    systemImage: "arrow.triangle.2.circlepath",
                    description: Text("Connecting to \(appState.machines.count) machine(s)")
                )
            }
        }
    }

    private var otherSessions: [Session] {
        appState.allSessions.filter { $0.state != .awaitingApproval }
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
        SessionListView()
    }
    .environment(AppState())
}
