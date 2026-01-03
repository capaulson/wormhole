import Foundation

/// A chat message in the session - either from user or AI
struct ChatMessage: Identifiable {
    enum Kind {
        case user(text: String)
        case ai(event: EventMessage)
    }

    let id: String
    let kind: Kind
    let timestamp: Date

    static func user(text: String) -> ChatMessage {
        ChatMessage(
            id: "user-\(UUID().uuidString)",
            kind: .user(text: text),
            timestamp: Date()
        )
    }

    static func ai(event: EventMessage) -> ChatMessage {
        ChatMessage(
            id: event.id,
            kind: .ai(event: event),
            timestamp: event.timestamp
        )
    }
}

/// Session state enum matching daemon states
enum SessionState: String, Codable {
    case idle
    case working
    case awaitingApproval = "awaiting_approval"
    case error

    var displayName: String {
        switch self {
        case .idle: return "Idle"
        case .working: return "Working"
        case .awaitingApproval: return "Awaiting Approval"
        case .error: return "Error"
        }
    }

    var badgeColor: String {
        switch self {
        case .idle: return "blue"
        case .working: return "yellow"
        case .awaitingApproval: return "purple"
        case .error: return "red"
        }
    }

    /// Sort priority - higher = should appear first
    var sortPriority: Int {
        switch self {
        case .awaitingApproval: return 3  // Needs attention first
        case .working: return 2
        case .error: return 1
        case .idle: return 0
        }
    }
}

/// A Claude Code session managed by the daemon
@Observable
final class Session: Identifiable {
    // Unique ID is now compound: machineId:sessionName
    var id: String { "\(machineId):\(name)" }

    let name: String
    let directory: String
    var state: SessionState
    var claudeSessionId: String?
    var costUsd: Double
    var lastActivity: Date
    var events: [EventMessage] = []
    var chatMessages: [ChatMessage] = []  // All messages in display order
    var pendingPermission: PermissionRequestMessage?
    var lastSeenSequence: Int = 0
    private var processedEventIds: Set<String> = []

    // Machine context - which machine this session belongs to
    let machineId: String
    var machineName: String
    var machineConnected: Bool = true

    /// Helper to check if an AI event has displayable content
    private func hasDisplayableContent(_ event: EventMessage) -> Bool {
        // Filter out system messages (init, success, etc.)
        if event.message["subtype"]?.value as? String != nil {
            return false
        }
        // Check if there's actual text content
        if let contentArray = event.message["content"]?.value as? [[String: Any]] {
            return contentArray.contains { item in
                (item["text"] as? String) != nil || item["type"] as? String == "tool_use"
            }
        }
        return false
    }

    /// Add a user message to the chat
    func addUserMessage(_ text: String) {
        let message = ChatMessage.user(text: text)
        chatMessages.append(message)
    }

    /// Add an AI event to the chat if it has displayable content
    func addEvent(_ event: EventMessage) {
        events.append(event)
        lastActivity = event.timestamp

        // Track highest seen sequence for sync
        lastSeenSequence = max(lastSeenSequence, event.sequence)

        // Only add to chat if it has content and hasn't been processed
        if hasDisplayableContent(event) && !processedEventIds.contains(event.id) {
            processedEventIds.insert(event.id)
            chatMessages.append(ChatMessage.ai(event: event))
        }
    }

    init(
        name: String,
        directory: String,
        machineId: String,
        machineName: String,
        state: SessionState = .idle,
        claudeSessionId: String? = nil,
        costUsd: Double = 0.0,
        lastActivity: Date = Date()
    ) {
        self.name = name
        self.directory = directory
        self.machineId = machineId
        self.machineName = machineName
        self.state = state
        self.claudeSessionId = claudeSessionId
        self.costUsd = costUsd
        self.lastActivity = lastActivity
    }

    /// Create session from server info with machine context
    convenience init(from info: SessionInfo, machineId: String, machineName: String) {
        self.init(
            name: info.name,
            directory: info.directory,
            machineId: machineId,
            machineName: machineName,
            state: SessionState(rawValue: info.state) ?? .idle,
            claudeSessionId: info.claudeSessionId,
            costUsd: info.costUsd,
            lastActivity: info.lastActivity ?? Date()
        )

        // Restore pending permission from reconnection recovery
        if let pendingInfo = info.pendingPermissions.first {
            self.pendingPermission = pendingInfo.toPermissionRequest()
        }
    }
}

extension Session: Hashable {
    static func == (lhs: Session, rhs: Session) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}
