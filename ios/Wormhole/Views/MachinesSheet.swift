import SwiftUI

/// Sheet for managing machine connections
struct MachinesSheet: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @State private var showingAddMachine = false

    var body: some View {
        NavigationStack {
            List {
                // Discovery status section
                Section {
                    DiscoveryStatusView(state: appState.discoveryState)
                }

                if appState.machines.isEmpty {
                    ContentUnavailableView(
                        "No Machines Found",
                        systemImage: "network",
                        description: Text("Looking for Wormhole daemons...\n\nMake sure the daemon is running on your network.")
                    )
                    .listRowBackground(Color.clear)
                } else {
                    Section("Machines") {
                        ForEach(appState.machines) { machine in
                            MachineRowView(machine: machine)
                        }
                    }
                }
            }
            .navigationTitle("Machines")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        showingAddMachine = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .sheet(isPresented: $showingAddMachine) {
                AddMachineView()
            }
        }
    }
}

/// Row displaying a machine with connection status
struct MachineRowView: View {
    @Environment(AppState.self) private var appState
    let machine: Machine

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(machine.connectionState.statusColor)
                        .frame(width: 10, height: 10)
                    Text(machine.displayName)
                        .font(.headline)
                }

                Text("\(machine.host):\(machine.port)")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if case .failed(let error) = machine.connectionState {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text(machine.connectionState.statusText)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if machine.sessionCount > 0 {
                    Text("\(machine.sessionCount) session\(machine.sessionCount == 1 ? "" : "s")")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            handleTap()
        }
    }

    private func handleTap() {
        switch machine.connectionState {
        case .connected:
            // Already connected - could show disconnect option
            appState.disconnectFromMachine(machine)
        case .connecting, .reconnecting:
            // In progress - do nothing
            break
        case .disconnected, .failed:
            // Try to connect
            Task {
                await appState.connectToMachine(machine)
            }
        }
    }
}

/// Discovery status indicator
struct DiscoveryStatusView: View {
    let state: DiscoveryState

    var body: some View {
        HStack(spacing: 12) {
            statusIndicator
            VStack(alignment: .leading, spacing: 2) {
                Text(statusTitle)
                    .font(.subheadline)
                    .fontWeight(.medium)
                Text(statusDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusIndicator: some View {
        switch state {
        case .idle:
            Image(systemName: "circle")
                .foregroundStyle(.secondary)
        case .browsing:
            ProgressView()
                .controlSize(.small)
        case .failed:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        }
    }

    private var statusTitle: String {
        switch state {
        case .idle:
            return "Discovery Stopped"
        case .browsing:
            return "Scanning Network"
        case .failed:
            return "Discovery Error"
        }
    }

    private var statusDescription: String {
        switch state {
        case .idle:
            return "Not searching for machines"
        case .browsing:
            return "Looking for Wormhole daemons via Bonjour"
        case .failed(let error):
            return error
        }
    }
}

/// Form to add a machine manually by IP/hostname
struct AddMachineView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var host = ""
    @State private var port = "7117"

    var isValid: Bool {
        !name.isEmpty && !host.isEmpty && Int(port) != nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Machine Details") {
                    TextField("Name", text: $name)
                        .textContentType(.name)
                        .autocorrectionDisabled()

                    TextField("Host (IP or hostname)", text: $host)
                        .textContentType(.URL)
                        .autocapitalization(.none)
                        .autocorrectionDisabled()

                    TextField("Port", text: $port)
                        .keyboardType(.numberPad)
                }

                Section {
                    Text("The machine must be running a Wormhole daemon. Default port is 7117.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Add Machine")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        if let portNum = Int(port) {
                            appState.addManualMachine(
                                host: host,
                                port: portNum,
                                name: name
                            )
                            dismiss()
                        }
                    }
                    .disabled(!isValid)
                }
            }
        }
    }
}

#Preview {
    MachinesSheet()
        .environment(AppState())
}
