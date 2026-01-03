import SwiftUI

/// Global app state using Observable macro - manages multi-machine connections
@MainActor
@Observable
final class AppState: MachineConnectionDelegate {
    // All discovered + manual machines
    var machines: [Machine] = []

    // Per-machine connections
    private var connections: [String: MachineConnection] = [:]

    // Discovery
    var discoveryState: DiscoveryState = .idle
    private var discoveryService: BonjourDiscoveryService?
    private var manualMachines: [Machine] = []

    // Error tracking
    var lastError: String?

    // MARK: - Computed Properties

    /// All sessions from all connected machines, sorted by priority
    var allSessions: [Session] {
        connections.values
            .flatMap { $0.sessions }
            .sorted { lhs, rhs in
                // Sort by state priority first (awaiting approval comes first)
                if lhs.state.sortPriority != rhs.state.sortPriority {
                    return lhs.state.sortPriority > rhs.state.sortPriority
                }
                // Then by last activity (most recent first)
                return lhs.lastActivity > rhs.lastActivity
            }
    }

    /// Whether any machine is connected
    var hasAnyConnection: Bool {
        connections.values.contains { $0.connectionState == .connected }
    }

    /// Summary of connection status
    var connectionSummary: String {
        let connected = connections.values.filter { $0.connectionState == .connected }.count
        let total = machines.count
        if total == 0 {
            return "No machines"
        }
        return "\(connected)/\(total) connected"
    }

    /// Sessions needing attention (awaiting approval)
    var sessionsNeedingAttention: [Session] {
        allSessions.filter { $0.state == .awaitingApproval }
    }

    // MARK: - Initialization

    init() {
        setupDiscoveryService()
    }

    private func setupDiscoveryService() {
        discoveryService = BonjourDiscoveryService()

        discoveryService?.onMachinesUpdated = { [weak self] discoveredMachines in
            guard let self = self else { return }
            // Merge discovered machines with manual ones
            let allMachines = discoveredMachines + self.manualMachines
            self.machines = allMachines

            // Auto-connect to all machines
            Task {
                await self.connectToAllMachines()
            }
        }

        discoveryService?.onStateChanged = { [weak self] state in
            self?.discoveryState = state
        }
    }

    // MARK: - Discovery

    func startDiscovery() {
        discoveryService?.startBrowsing()
    }

    func stopDiscovery() {
        discoveryService?.stopBrowsing()
    }

    // MARK: - Machine Management

    func addManualMachine(host: String, port: Int, name: String) {
        let machine = Machine(
            id: UUID().uuidString,
            name: name,
            host: host,
            port: port,
            isManual: true
        )
        manualMachines.append(machine)
        machines.append(machine)

        // Auto-connect to the new machine
        Task {
            await connectToMachine(machine)
        }
    }

    // MARK: - Connection Management

    /// Connect to all discovered machines
    func connectToAllMachines() async {
        for machine in machines {
            await connectToMachine(machine)
        }
    }

    /// Connect to a specific machine
    func connectToMachine(_ machine: Machine) async {
        // Skip if already connected or connecting
        if let existing = connections[machine.id] {
            if existing.connectionState == .connected || existing.connectionState == .connecting {
                return
            }
        }

        print("[AppState] Connecting to machine: \(machine.name) (\(machine.host):\(machine.port))")

        let connection = MachineConnection(machine: machine)
        connection.delegate = self
        connections[machine.id] = connection

        // Update machine state
        if let index = machines.firstIndex(where: { $0.id == machine.id }) {
            machines[index].connectionState = .connecting
        }

        await connection.connect()
    }

    /// Disconnect from a specific machine
    func disconnectFromMachine(_ machine: Machine) {
        guard let connection = connections[machine.id] else { return }

        connection.disconnect()
        // Don't remove connection - keep sessions visible in disconnected state

        if let index = machines.firstIndex(where: { $0.id == machine.id }) {
            machines[index].connectionState = .disconnected
        }
    }

    /// Disconnect from all machines
    func disconnectAll() {
        for connection in connections.values {
            connection.disconnect()
        }
    }

    // MARK: - Session Actions

    /// Find the connection for a session
    private func connectionForSession(_ sessionId: String) -> MachineConnection? {
        // Session ID format is "machineId:sessionName"
        let parts = sessionId.split(separator: ":", maxSplits: 1)
        guard parts.count >= 1 else { return nil }
        let machineId = String(parts[0])
        return connections[machineId]
    }

    /// Find a session by ID
    func session(byId id: String) -> Session? {
        allSessions.first { $0.id == id }
    }

    func sendInput(sessionId: String, text: String) async {
        guard let session = session(byId: sessionId),
              let connection = connectionForSession(sessionId) else { return }

        // Add user message to local chat and set state to working
        session.addUserMessage(text)
        session.state = .working

        await connection.sendInput(session: session.name, text: text)
    }

    func sendPermissionResponse(sessionId: String, requestId: String, decision: PermissionDecision) async {
        guard let session = session(byId: sessionId),
              let connection = connectionForSession(sessionId) else { return }

        // Clear the pending permission
        session.pendingPermission = nil
        session.state = .working

        await connection.sendPermissionResponse(requestId: requestId, decision: decision)
    }

    func sendControl(sessionId: String, action: ControlAction) async {
        guard let session = session(byId: sessionId),
              let connection = connectionForSession(sessionId) else { return }

        await connection.sendControl(session: session.name, action: action)
    }

    func requestSync(sessionId: String, lastSeenSequence: Int) async {
        guard let session = session(byId: sessionId),
              let connection = connectionForSession(sessionId) else { return }

        await connection.requestSync(session: session.name, lastSeenSequence: lastSeenSequence)
    }

    // MARK: - MachineConnectionDelegate

    nonisolated func connection(_ connection: MachineConnection, didUpdateState state: MachineConnectionState) {
        Task { @MainActor in
            print("[AppState] Connection \(connection.machine.name) state: \(state)")

            // Update machine state in our list
            if let index = machines.firstIndex(where: { $0.id == connection.machine.id }) {
                machines[index].connectionState = state
                machines[index].sessionCount = connection.sessions.count
            }

            // Track errors
            if case .failed(let error) = state {
                lastError = "\(connection.machine.name): \(error)"
            }
        }
    }

    nonisolated func connection(_ connection: MachineConnection, didReceiveMessage message: ServerMessage) {
        Task { @MainActor in
            // Handle any message types that need global state updates
            switch message {
            case .error(let error):
                lastError = error.message
            default:
                break
            }
        }
    }

    nonisolated func connection(_ connection: MachineConnection, didUpdateSessions sessions: [Session]) {
        Task { @MainActor in
            print("[AppState] Machine \(connection.machine.name) now has \(sessions.count) sessions")

            // Update session count in machine
            if let index = machines.firstIndex(where: { $0.id == connection.machine.id }) {
                machines[index].sessionCount = sessions.count
            }
        }
    }
}
