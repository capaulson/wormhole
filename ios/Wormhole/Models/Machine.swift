import Foundation
import SwiftUI

/// Connection state for a machine
enum MachineConnectionState: Equatable {
    case disconnected
    case connecting
    case connected
    case reconnecting
    case failed(String)

    var isConnected: Bool {
        self == .connected
    }

    var statusColor: Color {
        switch self {
        case .connected: return .green
        case .connecting, .reconnecting: return .orange
        case .disconnected: return .gray
        case .failed: return .red
        }
    }

    var statusText: String {
        switch self {
        case .disconnected: return "Disconnected"
        case .connecting: return "Connecting..."
        case .connected: return "Connected"
        case .reconnecting: return "Reconnecting..."
        case .failed(let error): return "Failed: \(error)"
        }
    }
}

/// Represents a discovered or manually added Wormhole daemon machine
struct Machine: Identifiable, Hashable {
    let id: String
    var name: String
    var host: String
    var port: Int
    var isManual: Bool = false

    // Connection state tracking
    var connectionState: MachineConnectionState = .disconnected
    var sessionCount: Int = 0

    var displayName: String {
        if isManual {
            return "\(name) (manual)"
        }
        return name
    }

    var connectionURL: URL? {
        URL(string: "ws://\(host):\(port)")
    }

    // Hashable conformance - only use stable identity properties
    static func == (lhs: Machine, rhs: Machine) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}
