import Foundation

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
}

/// A Claude Code session managed by the daemon
@Observable
final class Session: Identifiable {
    let id: String
    let name: String
    let directory: String
    var state: SessionState
    var claudeSessionId: String?
    var costUsd: Double
    var lastActivity: Date
    var events: [EventMessage] = []
    var pendingPermission: PermissionRequestMessage?
    var lastSeenSequence: Int = 0

    init(
        id: String = UUID().uuidString,
        name: String,
        directory: String,
        state: SessionState = .idle,
        claudeSessionId: String? = nil,
        costUsd: Double = 0.0,
        lastActivity: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.directory = directory
        self.state = state
        self.claudeSessionId = claudeSessionId
        self.costUsd = costUsd
        self.lastActivity = lastActivity
    }

    convenience init(from info: SessionInfo) {
        self.init(
            name: info.name,
            directory: info.directory,
            state: SessionState(rawValue: info.state) ?? .idle,
            claudeSessionId: info.claudeSessionId,
            costUsd: info.costUsd,
            lastActivity: info.lastActivity ?? Date()
        )
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
