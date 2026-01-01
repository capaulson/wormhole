import SwiftUI

@main
@MainActor
struct WormholeApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
        }
    }
}

/// Global app state using Observable macro
@MainActor
@Observable
final class AppState {
    var machines: [Machine] = []
    var selectedMachine: Machine?
    var sessions: [Session] = []
    var isConnected = false
    var connectionError: String?
    var discoveryState: DiscoveryState = .idle

    private var discoveryService: BonjourDiscoveryService?
    private var webSocketService: WebSocketService?
    private var manualMachines: [Machine] = []

    init() {
        setupDiscoveryService()
    }

    private func setupDiscoveryService() {
        discoveryService = BonjourDiscoveryService()

        discoveryService?.onMachinesUpdated = { [weak self] discoveredMachines in
            guard let self = self else { return }
            // Merge discovered machines with manual ones
            self.machines = discoveredMachines + self.manualMachines
        }

        discoveryService?.onStateChanged = { [weak self] state in
            self?.discoveryState = state
        }
    }

    func startDiscovery() {
        discoveryService?.startBrowsing()
    }

    func stopDiscovery() {
        discoveryService?.stopBrowsing()
    }

    func connect(to machine: Machine) async {
        selectedMachine = machine
        connectionError = nil

        webSocketService = WebSocketService(
            host: machine.host,
            port: machine.port
        )

        webSocketService?.onMessage = { [weak self] message in
            Task { @MainActor [weak self] in
                self?.handleMessage(message)
            }
        }

        webSocketService?.onConnectionChange = { [weak self] connected, error in
            Task { @MainActor [weak self] in
                self?.isConnected = connected
                self?.connectionError = error
                if !connected {
                    self?.sessions = []
                }
            }
        }

        await webSocketService?.connect()
    }

    func disconnect() {
        webSocketService?.disconnect()
        webSocketService = nil
        selectedMachine = nil
        sessions = []
        isConnected = false
    }

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
    }

    func sendInput(session: String, text: String) async {
        let message = InputMessage(session: session, text: text)
        await webSocketService?.send(message)
    }

    func sendPermissionResponse(requestId: String, decision: PermissionDecision) async {
        // Clear the pending permission from the session
        if let index = sessions.firstIndex(where: { $0.pendingPermission?.requestId == requestId }) {
            sessions[index].pendingPermission = nil
            sessions[index].state = .working
        }

        let message = PermissionResponseMessage(
            requestId: requestId,
            decision: decision
        )
        await webSocketService?.send(message)
    }

    func sendControl(session: String, action: ControlAction) async {
        let message = ControlMessage(session: session, action: action)
        await webSocketService?.send(message)
    }

    func requestSync(session: String, lastSeenSequence: Int) async {
        let message = SyncMessage(session: session, lastSeenSequence: lastSeenSequence)
        await webSocketService?.send(message)
    }

    private func handleMessage(_ message: ServerMessage) {
        print("[AppState] handleMessage: \(message)")
        switch message {
        case .welcome(let welcome):
            print("[AppState] Got welcome with \(welcome.sessions.count) sessions")
            sessions = welcome.sessions.map { Session(from: $0) }

        case .event(let event):
            print("[AppState] Got event for session \(event.session), sequence \(event.sequence)")
            if let index = sessions.firstIndex(where: { $0.name == event.session }) {
                sessions[index].events.append(event)
                sessions[index].lastActivity = event.timestamp
                print("[AppState] Session \(event.session) now has \(sessions[index].events.count) events")
            } else {
                print("[AppState] No session found for \(event.session)")
            }

        case .permissionRequest(let request):
            print("[AppState] Got permission request for \(request.sessionName)")
            if let index = sessions.firstIndex(where: { $0.name == request.sessionName }) {
                sessions[index].pendingPermission = request
                sessions[index].state = .awaitingApproval
            }

        case .syncResponse(let response):
            print("[AppState] Got sync response for \(response.session) with \(response.events.count) events")
            if let index = sessions.firstIndex(where: { $0.name == response.session }) {
                sessions[index].events.append(contentsOf: response.events)
            }

        case .error(let error):
            connectionError = error.message
        }
    }
}
