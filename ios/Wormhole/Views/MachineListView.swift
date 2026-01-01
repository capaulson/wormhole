import SwiftUI

struct MachineListView: View {
    @Environment(AppState.self) private var appState
    @State private var showingAddMachine = false

    var body: some View {
        List {
            // Discovery status section
            Section {
                DiscoveryStatusView(state: appState.discoveryState)
            }

            if appState.machines.isEmpty {
                ContentUnavailableView(
                    "No Machines Found",
                    systemImage: "network",
                    description: Text("Looking for Wormhole daemons on the network...\n\nTip: Make sure the daemon is running and you're on the same network.")
                )
                .listRowBackground(Color.clear)
            } else {
                Section("Available Machines") {
                    ForEach(appState.machines) { machine in
                        MachineRow(machine: machine)
                    }
                }
            }
        }
        .navigationTitle("Machines")
        .toolbar {
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
        .onAppear {
            appState.startDiscovery()
        }
        .onDisappear {
            appState.stopDiscovery()
        }
    }
}

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

struct MachineRow: View {
    @Environment(AppState.self) private var appState
    let machine: Machine

    var body: some View {
        Button {
            Task {
                await appState.connect(to: machine)
            }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(machine.displayName)
                        .font(.headline)
                    Text("\(machine.host):\(machine.port)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .foregroundStyle(.secondary)
            }
        }
        .buttonStyle(.plain)
    }
}

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
    NavigationStack {
        MachineListView()
    }
    .environment(AppState())
}
