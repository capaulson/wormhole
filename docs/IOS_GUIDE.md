# iOS Implementation Guide

## Project Setup

### Xcode Project Configuration

Create new Xcode project with these settings:
- **Product Name**: Wormhole
- **Organization Identifier**: com.yourname (or your domain)
- **Interface**: SwiftUI
- **Language**: Swift
- **Minimum Deployment**: iOS 17.0
- **Include Tests**: Yes (both Unit and UI)

### Required Capabilities

In Signing & Capabilities:
- **Bonjour Services**: Add `_wormhole._tcp`
- **Background Modes**: None needed for V1

### Info.plist Additions

```xml
<key>NSBonjourServices</key>
<array>
    <string>_wormhole._tcp</string>
</array>
<key>NSLocalNetworkUsageDescription</key>
<string>Wormhole needs local network access to discover and connect to development machines running the Wormhole daemon.</string>
```

### No External Dependencies

V1 uses only system frameworks:
- `Foundation`
- `SwiftUI`
- `Network` (for NWBrowser)
- `Observation`

No SPM packages needed.

---

## File Structure

```
Wormhole/
├── WormholeApp.swift
├── ContentView.swift
│
├── Models/
│   ├── Machine.swift           # Discovered/saved machines
│   ├── Session.swift           # Session state
│   ├── Message.swift           # Protocol messages (Codable)
│   └── AppState.swift          # Global observable state
│
├── Views/
│   ├── MachineListView.swift   # List of machines
│   ├── MachineRow.swift        # Single machine row
│   ├── SessionListView.swift   # Sessions on a machine
│   ├── SessionRow.swift        # Single session row
│   ├── SessionView.swift       # Main interaction view
│   ├── EventStreamView.swift   # Scrollable event list
│   ├── EventRow.swift          # Single event rendering
│   ├── PermissionCard.swift    # Permission request UI
│   ├── QuickActionBar.swift    # Bottom action buttons
│   ├── AddMachineSheet.swift   # Manual machine entry
│   └── SettingsView.swift      # App settings
│
├── Services/
│   ├── DiscoveryService.swift  # Bonjour discovery
│   ├── WebSocketClient.swift   # WebSocket connection
│   ├── ConnectionManager.swift # Manage multiple connections
│   └── SessionManager.swift    # Session state management
│
└── Resources/
    └── Assets.xcassets
        ├── AppIcon.appiconset
        └── Colors/
```

---

## Model Definitions

### Machine.swift

```swift
import Foundation
import Observation

@Observable
final class Machine: Identifiable, Hashable {
    let id: UUID
    var name: String
    var host: String
    var port: Int
    var isDiscovered: Bool  // vs manually added
    var connectionState: ConnectionState = .disconnected
    var sessions: [Session] = []
    var lastSeen: Date?
    
    enum ConnectionState: String {
        case disconnected
        case connecting
        case connected
        case error
    }
    
    init(id: UUID = UUID(), name: String, host: String, port: Int = 7117, isDiscovered: Bool) {
        self.id = id
        self.name = name
        self.host = host
        self.port = port
        self.isDiscovered = isDiscovered
    }
    
    static func == (lhs: Machine, rhs: Machine) -> Bool {
        lhs.id == rhs.id
    }
    
    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}
```

### Session.swift

```swift
import Foundation
import Observation

@Observable
final class Session: Identifiable, Hashable {
    let id: UUID
    let name: String
    let directory: String
    var claudeSessionId: String?
    var state: SessionState = .idle
    var costUSD: Double = 0.0
    var lastActivity: Date?
    var events: [SessionEvent] = []
    var lastSeenSequence: Int = 0
    var pendingPermission: PermissionRequest?
    
    enum SessionState: String, Codable {
        case idle
        case working
        case awaitingApproval = "awaiting_approval"
        case error
    }
    
    init(name: String, directory: String) {
        self.id = UUID()
        self.name = name
        self.directory = directory
    }
    
    static func == (lhs: Session, rhs: Session) -> Bool {
        lhs.id == rhs.id
    }
    
    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

struct SessionEvent: Identifiable {
    let id: UUID
    let sequence: Int
    let timestamp: Date
    let message: ServerMessage
    
    init(sequence: Int, timestamp: Date, message: ServerMessage) {
        self.id = UUID()
        self.sequence = sequence
        self.timestamp = timestamp
        self.message = message
    }
}
```

### Message.swift

```swift
import Foundation

// MARK: - Client -> Server

protocol ClientMessage: Encodable {
    var type: String { get }
}

struct HelloMessage: ClientMessage {
    let type = "hello"
    let clientVersion: String
    let deviceName: String
    
    enum CodingKeys: String, CodingKey {
        case type
        case clientVersion = "client_version"
        case deviceName = "device_name"
    }
}

struct SubscribeMessage: ClientMessage {
    let type = "subscribe"
    let sessions: SessionSelector
    
    enum SessionSelector: Encodable {
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
    }
}

struct InputMessage: ClientMessage {
    let type = "input"
    let session: String
    let text: String
}

struct PermissionResponseMessage: ClientMessage {
    let type = "permission_response"
    let requestId: String
    let decision: Decision
    
    enum Decision: String, Encodable {
        case allow
        case deny
    }
    
    enum CodingKeys: String, CodingKey {
        case type
        case requestId = "request_id"
        case decision
    }
}

struct ControlMessage: ClientMessage {
    let type = "control"
    let session: String
    let action: Action
    
    enum Action: String, Encodable {
        case interrupt
        case compact
        case clear
        case plan
    }
}

struct SyncMessage: ClientMessage {
    let type = "sync"
    let session: String
    let lastSeenSequence: Int
    
    enum CodingKeys: String, CodingKey {
        case type
        case session
        case lastSeenSequence = "last_seen_sequence"
    }
}

// MARK: - Server -> Client

enum ServerMessage: Decodable {
    case welcome(WelcomePayload)
    case event(EventPayload)
    case permissionRequest(PermissionRequestPayload)
    case syncResponse(SyncResponsePayload)
    case error(ErrorPayload)
    
    enum CodingKeys: String, CodingKey {
        case type
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)
        
        switch type {
        case "welcome":
            self = .welcome(try WelcomePayload(from: decoder))
        case "event":
            self = .event(try EventPayload(from: decoder))
        case "permission_request":
            self = .permissionRequest(try PermissionRequestPayload(from: decoder))
        case "sync_response":
            self = .syncResponse(try SyncResponsePayload(from: decoder))
        case "error":
            self = .error(try ErrorPayload(from: decoder))
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .type,
                in: container,
                debugDescription: "Unknown message type: \(type)"
            )
        }
    }
}

struct WelcomePayload: Decodable {
    let serverVersion: String
    let machineName: String
    let sessions: [SessionInfo]
    
    struct SessionInfo: Decodable {
        let name: String
        let directory: String
        let state: Session.SessionState
        let claudeSessionId: String?
        let costUsd: Double
        let lastActivity: Date?
        
        enum CodingKeys: String, CodingKey {
            case name, directory, state
            case claudeSessionId = "claude_session_id"
            case costUsd = "cost_usd"
            case lastActivity = "last_activity"
        }
    }
    
    enum CodingKeys: String, CodingKey {
        case serverVersion = "server_version"
        case machineName = "machine_name"
        case sessions
    }
}

struct EventPayload: Decodable {
    let session: String
    let sequence: Int
    let timestamp: Date
    let message: SDKMessage
}

struct SDKMessage: Decodable {
    let type: String
    let subtype: String?
    let raw: [String: AnyCodable]  // Preserve full message
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        
        self.type = try container.decode(String.self, forKey: DynamicCodingKey(stringValue: "type")!)
        self.subtype = try container.decodeIfPresent(String.self, forKey: DynamicCodingKey(stringValue: "subtype")!)
        
        var raw: [String: AnyCodable] = [:]
        for key in container.allKeys {
            raw[key.stringValue] = try container.decode(AnyCodable.self, forKey: key)
        }
        self.raw = raw
    }
}

struct PermissionRequestPayload: Decodable {
    let requestId: String
    let toolName: String
    let toolInput: [String: AnyCodable]
    let sessionName: String
    
    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case toolName = "tool_name"
        case toolInput = "tool_input"
        case sessionName = "session_name"
    }
}

struct SyncResponsePayload: Decodable {
    let session: String
    let events: [EventPayload]
}

struct ErrorPayload: Decodable {
    let code: String
    let message: String
    let session: String?
}

// MARK: - Helpers

struct DynamicCodingKey: CodingKey {
    var stringValue: String
    var intValue: Int?
    
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { self.intValue = intValue; self.stringValue = "\(intValue)" }
}

struct AnyCodable: Decodable {
    let value: Any
    
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
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported type")
        }
    }
}

// Convenience for permission requests
struct PermissionRequest: Identifiable {
    let id: String  // requestId
    let toolName: String
    let toolInput: [String: Any]
    let sessionName: String
    
    init(from payload: PermissionRequestPayload) {
        self.id = payload.requestId
        self.toolName = payload.toolName
        self.toolInput = payload.toolInput.mapValues { $0.value }
        self.sessionName = payload.sessionName
    }
}
```

---

## Service Implementations

### DiscoveryService.swift

```swift
import Foundation
import Network
import Observation

@Observable
final class DiscoveryService {
    private(set) var discoveredMachines: [Machine] = []
    private var browser: NWBrowser?
    private var isRunning = false
    
    func start() {
        guard !isRunning else { return }
        isRunning = true
        
        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        
        browser = NWBrowser(for: .bonjour(type: "_wormhole._tcp", domain: nil), using: parameters)
        
        browser?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                print("Discovery ready")
            case .failed(let error):
                print("Discovery failed: \(error)")
                self?.isRunning = false
            default:
                break
            }
        }
        
        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            self?.handleResults(results)
        }
        
        browser?.start(queue: .main)
    }
    
    func stop() {
        browser?.cancel()
        browser = nil
        isRunning = false
    }
    
    private func handleResults(_ results: Set<NWBrowser.Result>) {
        var machines: [Machine] = []
        
        for result in results {
            if case .service(let name, let type, let domain, _) = result.endpoint {
                // Resolve endpoint to get host/port
                let machine = Machine(
                    name: name,
                    host: "\(name).local",  // Will resolve via mDNS
                    port: 7117,  // Default, could parse from TXT record
                    isDiscovered: true
                )
                machines.append(machine)
            }
        }
        
        self.discoveredMachines = machines
    }
}
```

### WebSocketClient.swift

```swift
import Foundation
import Observation

@Observable
final class WebSocketClient {
    private(set) var state: State = .disconnected
    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession?
    private var receiveTask: Task<Void, Never>?
    
    var onMessage: ((ServerMessage) -> Void)?
    var onDisconnect: (() -> Void)?
    
    enum State {
        case disconnected
        case connecting
        case connected
        case error(String)
    }
    
    func connect(to machine: Machine) {
        guard case .disconnected = state else { return }
        state = .connecting
        
        let url = URL(string: "ws://\(machine.host):\(machine.port)/ws")!
        session = URLSession(configuration: .default)
        webSocket = session?.webSocketTask(with: url)
        webSocket?.resume()
        
        // Send hello
        let hello = HelloMessage(
            clientVersion: "1.0.0",
            deviceName: UIDevice.current.name
        )
        send(hello)
        
        state = .connected
        startReceiving()
    }
    
    func disconnect() {
        receiveTask?.cancel()
        webSocket?.cancel(with: .normalClosure, reason: nil)
        webSocket = nil
        session = nil
        state = .disconnected
    }
    
    func send<T: ClientMessage>(_ message: T) {
        guard let webSocket else { return }
        
        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let data = try encoder.encode(message)
            let string = String(data: data, encoding: .utf8)!
            
            webSocket.send(.string(string)) { error in
                if let error {
                    print("Send error: \(error)")
                }
            }
        } catch {
            print("Encode error: \(error)")
        }
    }
    
    private func startReceiving() {
        receiveTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let webSocket = self?.webSocket else { break }
                
                do {
                    let message = try await webSocket.receive()
                    
                    switch message {
                    case .string(let text):
                        self?.handleMessage(text)
                    case .data(let data):
                        if let text = String(data: data, encoding: .utf8) {
                            self?.handleMessage(text)
                        }
                    @unknown default:
                        break
                    }
                } catch {
                    await MainActor.run {
                        self?.state = .error(error.localizedDescription)
                        self?.onDisconnect?()
                    }
                    break
                }
            }
        }
    }
    
    private func handleMessage(_ text: String) {
        do {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            decoder.dateDecodingStrategy = .iso8601
            
            let message = try decoder.decode(ServerMessage.self, from: Data(text.utf8))
            
            Task { @MainActor in
                self.onMessage?(message)
            }
        } catch {
            print("Decode error: \(error)")
        }
    }
}
```

---

## View Implementations

### QuickActionBar.swift

```swift
import SwiftUI

struct QuickActionBar: View {
    let session: Session
    let onAction: (Action) -> Void
    
    enum Action {
        case interrupt
        case allow
        case deny
        case plan
        case compact
        case clear
    }
    
    var body: some View {
        HStack(spacing: 12) {
            switch session.state {
            case .working:
                actionButton("Stop", systemImage: "stop.fill", tint: .red) {
                    onAction(.interrupt)
                }
                
            case .awaitingApproval:
                actionButton("Deny", systemImage: "xmark.circle.fill", tint: .red) {
                    onAction(.deny)
                }
                actionButton("Allow", systemImage: "checkmark.circle.fill", tint: .green) {
                    onAction(.allow)
                }
                
            case .idle, .error:
                EmptyView()
            }
            
            Spacer()
            
            Menu {
                Button("Plan Mode", systemImage: "list.bullet.clipboard") {
                    onAction(.plan)
                }
                Button("Compact", systemImage: "arrow.down.right.and.arrow.up.left") {
                    onAction(.compact)
                }
                Button("Clear", systemImage: "trash", role: .destructive) {
                    onAction(.clear)
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title2)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }
    
    private func actionButton(
        _ title: String,
        systemImage: String,
        tint: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.headline)
        }
        .buttonStyle(.borderedProminent)
        .tint(tint)
    }
}
```

### PermissionCard.swift

```swift
import SwiftUI

struct PermissionCard: View {
    let request: PermissionRequest
    let onAllow: () -> Void
    let onDeny: () -> Void
    
    @State private var isExpanded = false
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Header
            HStack {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.yellow)
                Text("Permission Required")
                    .font(.headline)
                Spacer()
            }
            
            // Tool info
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Tool:")
                        .foregroundStyle(.secondary)
                    Text(request.toolName)
                        .fontWeight(.medium)
                }
                
                if let filePath = request.toolInput["file_path"] as? String {
                    HStack {
                        Text("File:")
                            .foregroundStyle(.secondary)
                        Text(filePath)
                            .font(.system(.body, design: .monospaced))
                            .lineLimit(1)
                    }
                }
            }
            
            // Content preview (expandable)
            if let content = request.toolInput["content"] as? String {
                DisclosureGroup("Content Preview", isExpanded: $isExpanded) {
                    ScrollView {
                        Text(content)
                            .font(.system(.caption, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 150)
                }
            }
            
            // Actions
            HStack(spacing: 16) {
                Button(action: onDeny) {
                    Label("Deny", systemImage: "xmark.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                
                Button(action: onAllow) {
                    Label("Allow", systemImage: "checkmark.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
            }
        }
        .padding()
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(radius: 4)
    }
}
```

---

## Testing

### Test with Mock Server

For unit testing without a real daemon, create a mock WebSocket server:

```swift
// Tests/Mocks/MockWebSocketServer.swift
import Foundation
import Network

class MockWebSocketServer {
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    
    let port: UInt16
    var onMessage: ((String) -> Void)?
    
    init(port: UInt16 = 7117) {
        self.port = port
    }
    
    func start() throws {
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true
        
        listener = try NWListener(using: parameters, on: NWEndpoint.Port(integerLiteral: port))
        
        listener?.newConnectionHandler = { [weak self] connection in
            self?.handleConnection(connection)
        }
        
        listener?.start(queue: .main)
    }
    
    func stop() {
        connections.forEach { $0.cancel() }
        listener?.cancel()
    }
    
    func send(_ message: String) {
        let data = Data(message.utf8)
        connections.forEach { conn in
            conn.send(content: data, completion: .idempotent)
        }
    }
    
    func sendWelcome() {
        let welcome = """
        {"type":"welcome","server_version":"1.0.0","machine_name":"test","sessions":[]}
        """
        send(welcome)
    }
    
    private func handleConnection(_ connection: NWConnection) {
        connections.append(connection)
        connection.start(queue: .main)
        receiveMessage(on: connection)
    }
    
    private func receiveMessage(on connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, _, error in
            if let data, let text = String(data: data, encoding: .utf8) {
                self?.onMessage?(text)
            }
            if error == nil {
                self?.receiveMessage(on: connection)
            }
        }
    }
}
```

### Sample Tests

```swift
// Tests/WebSocketClientTests.swift
import Testing
@testable import Wormhole

@Suite("WebSocket Client Tests")
struct WebSocketClientTests {
    
    @Test("Connects and receives welcome")
    func connectAndReceiveWelcome() async throws {
        let server = MockWebSocketServer()
        try server.start()
        defer { server.stop() }
        
        let client = WebSocketClient()
        let machine = Machine(name: "test", host: "localhost", port: 7117, isDiscovered: false)
        
        var receivedWelcome = false
        client.onMessage = { message in
            if case .welcome = message {
                receivedWelcome = true
            }
        }
        
        client.connect(to: machine)
        
        // Server sends welcome after hello
        try await Task.sleep(for: .milliseconds(100))
        server.sendWelcome()
        try await Task.sleep(for: .milliseconds(100))
        
        #expect(receivedWelcome)
    }
}
```

---

## UI/UX Guidelines

### Colors
- Use system colors (`.primary`, `.secondary`, `.red`, `.green`)
- No custom color palette for V1

### Icons
- Use SF Symbols exclusively
- Key icons:
  - Machine: `desktopcomputer`
  - Session: `terminal`
  - Working: `circle.dotted` (with animation)
  - Awaiting: `exclamationmark.circle`
  - Idle: `circle`
  - Error: `xmark.circle`
  - Connected: `wifi`
  - Disconnected: `wifi.slash`

### Haptics
- Success (allow): `.success`
- Error (deny): `.error`
- Permission request: `.warning`

```swift
import UIKit

func triggerHaptic(_ type: UINotificationFeedbackGenerator.FeedbackType) {
    let generator = UINotificationFeedbackGenerator()
    generator.notificationOccurred(type)
}
```

### Auto-scroll
Event stream should auto-scroll to bottom when new events arrive, but stop if user scrolls up.

```swift
struct EventStreamView: View {
    let events: [SessionEvent]
    @State private var isAtBottom = true
    
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(events) { event in
                        EventRow(event: event)
                            .id(event.id)
                    }
                }
                .onChange(of: events.count) { _, _ in
                    if isAtBottom, let last = events.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }
        }
    }
}
```

---

## Checklist Before Submitting to TestFlight

- [ ] App icon set (all sizes)
- [ ] Launch screen configured
- [ ] Info.plist has all required keys
- [ ] Privacy manifest if needed (none for V1)
- [ ] No crashes in basic flow
- [ ] Works on iPhone SE (small screen)
- [ ] Works on iPhone 15 Pro Max (large screen)
- [ ] Dark mode looks correct
- [ ] VoiceOver accessible (basic)
- [ ] No hardcoded localhost (use discovered/entered hosts)
