import Foundation

/// Represents a discovered or manually added Wormhole daemon machine
struct Machine: Identifiable, Hashable {
    let id: String
    var name: String
    var host: String
    var port: Int
    var isManual: Bool = false

    var displayName: String {
        if isManual {
            return "\(name) (manual)"
        }
        return name
    }

    var connectionURL: URL? {
        URL(string: "ws://\(host):\(port)")
    }
}
