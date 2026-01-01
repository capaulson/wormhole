import SwiftUI

struct MachineListView: View {
    @Environment(AppState.self) private var appState
    @State private var showingAddMachine = false

    var body: some View {
        List {
            if appState.machines.isEmpty {
                ContentUnavailableView(
                    "No Machines Found",
                    systemImage: "network",
                    description: Text("Looking for Wormhole daemons on the network...")
                )
                .listRowBackground(Color.clear)
            } else {
                ForEach(appState.machines) { machine in
                    MachineRow(machine: machine)
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
