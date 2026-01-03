import Foundation

/// Protocol for MachineConnection to report events back to AppState
protocol MachineConnectionDelegate: AnyObject {
    func connection(_ connection: MachineConnection, didUpdateState state: MachineConnectionState)
    func connection(_ connection: MachineConnection, didReceiveMessage message: ServerMessage)
    func connection(_ connection: MachineConnection, didUpdateSessions sessions: [Session])
}

/// Manages WebSocket connection and sessions for a single machine
@MainActor
@Observable
final class MachineConnection: Identifiable {
    let id: String
    let machine: Machine
    private var webSocketService: WebSocketService?

    var sessions: [Session] = []
    private(set) var connectionState: MachineConnectionState = .disconnected
    var lastError: String?

    weak var delegate: MachineConnectionDelegate?

    init(machine: Machine) {
        self.id = machine.id
        self.machine = machine
    }

    func connect() async {
        guard connectionState != .connected && connectionState != .connecting else { return }

        connectionState = .connecting
        delegate?.connection(self, didUpdateState: connectionState)

        webSocketService = WebSocketService(host: machine.host, port: machine.port)

        webSocketService?.onMessage = { [weak self] message in
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                self.handleMessage(message)
            }
        }

        webSocketService?.onConnectionChange = { [weak self] connected, error in
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                if connected {
                    self.connectionState = .connected
                    self.lastError = nil
                    // Mark all sessions as connected
                    for session in self.sessions {
                        session.machineConnected = true
                    }
                } else if let error = error {
                    self.connectionState = .failed(error)
                    self.lastError = error
                    // Mark all sessions as disconnected
                    for session in self.sessions {
                        session.machineConnected = false
                    }
                } else {
                    self.connectionState = .disconnected
                    for session in self.sessions {
                        session.machineConnected = false
                    }
                }
                self.delegate?.connection(self, didUpdateState: self.connectionState)
            }
        }

        await webSocketService?.connect()
    }

    func disconnect() {
        webSocketService?.disconnect()
        webSocketService = nil
        connectionState = .disconnected
        // DON'T clear sessions - preserve for display in disconnected state
        for session in sessions {
            session.machineConnected = false
        }
        delegate?.connection(self, didUpdateState: connectionState)
    }

    func send<T: Encodable>(_ message: T) async {
        await webSocketService?.send(message)
    }

    func requestSync(session: String, lastSeenSequence: Int) async {
        let message = SyncMessage(session: session, lastSeenSequence: lastSeenSequence)
        await send(message)
    }

    func sendInput(session: String, text: String) async {
        let message = InputMessage(session: session, text: text)
        await send(message)
    }

    func sendPermissionResponse(requestId: String, decision: PermissionDecision) async {
        let message = PermissionResponseMessage(requestId: requestId, decision: decision)
        await send(message)
    }

    func sendControl(session: String, action: ControlAction) async {
        let message = ControlMessage(session: session, action: action)
        await send(message)
    }

    // MARK: - Message Handling

    private func handleMessage(_ message: ServerMessage) {
        // Forward all messages to delegate
        delegate?.connection(self, didReceiveMessage: message)

        switch message {
        case .welcome(let welcome):
            handleWelcome(welcome)

        case .event(let event):
            handleEvent(event)

        case .permissionRequest(let request):
            handlePermissionRequest(request)

        case .syncResponse(let response):
            handleSyncResponse(response)

        case .error(let error):
            handleError(error)
        }
    }

    private func handleWelcome(_ welcome: WelcomeMessage) {
        // Create sessions from welcome message
        sessions = welcome.sessions.map { info in
            Session(from: info, machineId: machine.id, machineName: machine.name)
        }

        delegate?.connection(self, didUpdateSessions: sessions)

        // CRITICAL: Request full history for each session immediately
        // This fixes the bug where history wasn't loading on first connect
        Task {
            for session in sessions {
                // Sequence 0 = request all available events
                await requestSync(session: session.name, lastSeenSequence: 0)
            }
        }
    }

    private func handleEvent(_ event: EventMessage) {
        guard let session = sessions.first(where: { $0.name == event.session }) else {
            return
        }

        session.addEvent(event)

        // Update state from event if present
        if let stateStr = event.message["state"]?.value as? String,
           let newState = SessionState(rawValue: stateStr) {
            session.state = newState
        }

        // Detect result message (Claude finished) - set state to idle
        if let msgType = event.message["type"]?.value as? String, msgType == "result" {
            session.state = .idle
            session.pendingPermission = nil  // Clear any pending permission
        }
    }

    private func handlePermissionRequest(_ request: PermissionRequestMessage) {
        guard let session = sessions.first(where: { $0.name == request.sessionName }) else {
            return
        }

        session.pendingPermission = request
        session.state = .awaitingApproval
    }

    private func handleSyncResponse(_ response: SyncResponseMessage) {
        guard let session = sessions.first(where: { $0.name == response.session }) else {
            return
        }

        // Add all events from sync response
        for event in response.events {
            session.addEvent(event)
        }

        // Restore pending permissions if present
        if let pendingInfo = response.pendingPermissions.first {
            session.pendingPermission = pendingInfo.toPermissionRequest()
            session.state = .awaitingApproval
        }
    }

    private func handleError(_ error: ErrorMessageResponse) {
        lastError = error.message

        if let sessionName = error.session,
           let session = sessions.first(where: { $0.name == sessionName }) {
            session.state = .error
        }
    }
}
