import Foundation

// MARK: - Client -> Server Messages

/// Hello message sent on connection
struct HelloMessage: Codable, Sendable {
    let type: String = "hello"
    let clientVersion: String
    let deviceName: String

    enum CodingKeys: String, CodingKey {
        case type
        case clientVersion = "client_version"
        case deviceName = "device_name"
    }
}

/// Subscribe to session events
struct SubscribeMessage: Codable, Sendable {
    let type: String = "subscribe"
    let sessions: SubscribeSessions

    enum SubscribeSessions: Codable, Sendable {
        case all
        case specific([String])

        func encode(to encoder: Encoder) throws {
            var container = encoder.singleValueContainer()
            switch self {
            case .all:
                try container.encode("*")
            case .specific(let names):
                try container.encode(names)
            }
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let star = try? container.decode(String.self), star == "*" {
                self = .all
            } else {
                self = .specific(try container.decode([String].self))
            }
        }
    }
}

/// Send text input to a session
struct InputMessage: Codable, Sendable {
    let type: String = "input"
    let session: String
    let text: String
}

/// Permission decision
enum PermissionDecision: String, Codable, Sendable {
    case allow
    case deny
}

/// Response to a permission request
struct PermissionResponseMessage: Codable, Sendable {
    let type: String = "permission_response"
    let requestId: String
    let decision: PermissionDecision

    enum CodingKeys: String, CodingKey {
        case type
        case requestId = "request_id"
        case decision
    }
}

/// Control action for a session
enum ControlAction: String, Codable, Sendable {
    case interrupt
    case compact
    case clear
    case plan
}

/// Control message for session actions
struct ControlMessage: Codable, Sendable {
    let type: String = "control"
    let session: String
    let action: ControlAction
}

/// Request sync of events since a sequence number
struct SyncMessage: Codable, Sendable {
    let type: String = "sync"
    let session: String
    let lastSeenSequence: Int

    enum CodingKeys: String, CodingKey {
        case type
        case session
        case lastSeenSequence = "last_seen_sequence"
    }
}

/// Union type for all client messages
enum ClientMessage: Codable, Sendable {
    case hello(HelloMessage)
    case subscribe(SubscribeMessage)
    case input(InputMessage)
    case permissionResponse(PermissionResponseMessage)
    case control(ControlMessage)
    case sync(SyncMessage)
}

// MARK: - Server -> Client Messages

/// Session info in welcome message
struct SessionInfo: Codable, Sendable {
    let name: String
    let directory: String
    let state: String
    let claudeSessionId: String?
    let costUsd: Double
    let lastActivity: Date

    enum CodingKeys: String, CodingKey {
        case name
        case directory
        case state
        case claudeSessionId = "claude_session_id"
        case costUsd = "cost_usd"
        case lastActivity = "last_activity"
    }
}

/// Welcome message received after hello
struct WelcomeMessage: Codable, Sendable {
    let type: String
    let serverVersion: String
    let machineName: String
    let sessions: [SessionInfo]

    enum CodingKeys: String, CodingKey {
        case type
        case serverVersion = "server_version"
        case machineName = "machine_name"
        case sessions
    }
}

/// Event from a session
struct EventMessage: Codable, Sendable, Identifiable {
    var id: String { "\(session)-\(sequence)" }

    let type: String
    let session: String
    let sequence: Int
    let timestamp: Date
    let message: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case type
        case session
        case sequence
        case timestamp
        case message
    }
}

/// Permission request from daemon
struct PermissionRequestMessage: Codable, Sendable, Identifiable {
    var id: String { requestId }

    let type: String
    let requestId: String
    let toolName: String
    let toolInput: [String: AnyCodable]
    let sessionName: String

    enum CodingKeys: String, CodingKey {
        case type
        case requestId = "request_id"
        case toolName = "tool_name"
        case toolInput = "tool_input"
        case sessionName = "session_name"
    }
}

/// Sync response with events
struct SyncResponseMessage: Codable, Sendable {
    let type: String
    let session: String
    let events: [EventMessage]
}

/// Error message from daemon
struct ErrorMessageResponse: Codable, Sendable {
    let type: String
    let code: String
    let message: String
    let session: String?
}

/// Union type for all server messages
enum ServerMessage: Sendable {
    case welcome(WelcomeMessage)
    case event(EventMessage)
    case permissionRequest(PermissionRequestMessage)
    case syncResponse(SyncResponseMessage)
    case error(ErrorMessageResponse)
}

extension ServerMessage: Codable {
    enum CodingKeys: String, CodingKey {
        case type
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        let singleValueContainer = try decoder.singleValueContainer()

        switch type {
        case "welcome":
            self = .welcome(try singleValueContainer.decode(WelcomeMessage.self))
        case "event":
            self = .event(try singleValueContainer.decode(EventMessage.self))
        case "permission_request":
            self = .permissionRequest(try singleValueContainer.decode(PermissionRequestMessage.self))
        case "sync_response":
            self = .syncResponse(try singleValueContainer.decode(SyncResponseMessage.self))
        case "error":
            self = .error(try singleValueContainer.decode(ErrorMessageResponse.self))
        default:
            throw DecodingError.dataCorrupted(
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "Unknown message type: \(type)"
                )
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .welcome(let msg): try container.encode(msg)
        case .event(let msg): try container.encode(msg)
        case .permissionRequest(let msg): try container.encode(msg)
        case .syncResponse(let msg): try container.encode(msg)
        case .error(let msg): try container.encode(msg)
        }
    }
}

// MARK: - AnyCodable helper for dynamic JSON

struct AnyCodable: Codable, Sendable, Hashable {
    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode AnyCodable"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(String(describing: value))
    }
}
