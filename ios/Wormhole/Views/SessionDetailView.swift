import SwiftUI

struct SessionDetailView: View {
    @Environment(AppState.self) private var appState
    @Bindable var session: Session

    var body: some View {
        VStack(spacing: 0) {
            // Event stream
            EventStreamView(session: session)

            // Permission card if awaiting approval
            if let permission = session.pendingPermission {
                PermissionCardView(
                    session: session,
                    permission: permission
                )
            }

            // Input bar
            InputBarView(session: session)
        }
        .navigationTitle(session.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button {
                        Task {
                            await appState.sendControl(session: session.name, action: .interrupt)
                        }
                    } label: {
                        Label("Stop", systemImage: "stop.fill")
                    }

                    Button {
                        Task {
                            await appState.sendControl(session: session.name, action: .plan)
                        }
                    } label: {
                        Label("Plan Mode", systemImage: "list.bullet.clipboard")
                    }

                    Button {
                        Task {
                            await appState.sendControl(session: session.name, action: .compact)
                        }
                    } label: {
                        Label("Compact", systemImage: "arrow.down.left.and.arrow.up.right")
                    }

                    Divider()

                    Button(role: .destructive) {
                        Task {
                            await appState.sendControl(session: session.name, action: .clear)
                        }
                    } label: {
                        Label("Clear", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .onAppear {
            // Request sync if we have a last seen sequence
            if session.lastSeenSequence > 0 {
                Task {
                    await appState.requestSync(
                        session: session.name,
                        lastSeenSequence: session.lastSeenSequence
                    )
                }
            }
        }
    }
}

struct EventStreamView: View {
    @Bindable var session: Session

    /// Filter out init, success, and other system messages that aren't useful to display
    var displayableEvents: [EventMessage] {
        session.events.filter { event in
            // Filter out system messages (init, success, etc.)
            if let subtype = event.message["subtype"]?.value as? String {
                return false  // Hide all subtype messages (init, success, etc.)
            }
            return true
        }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(displayableEvents) { event in
                        EventRowView(event: event)
                            .id(event.id)
                    }
                }
                .padding()
            }
            .onChange(of: session.events.count) { _, _ in
                if let lastEvent = displayableEvents.last {
                    withAnimation {
                        proxy.scrollTo(lastEvent.id, anchor: .bottom)
                    }
                }
            }
        }
    }
}

struct EventRowView: View {
    let event: EventMessage

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            // Extract message type if available
            if let type = event.message["type"]?.value as? String {
                HStack {
                    Text(type)
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Spacer()

                    Text(event.timestamp, style: .time)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            // Display content based on message type
            if let content = extractContent(from: event.message) {
                Text(content)
                    .font(.body)
            }
        }
        .padding(8)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    func extractContent(from message: [String: AnyCodable]) -> String? {
        // Try to extract text content from assistant messages
        // The content array is directly in message["content"], not message["message"]["content"]
        if let contentArray = message["content"]?.value as? [[String: Any]] {
            let texts = contentArray.compactMap { item -> String? in
                if let text = item["text"] as? String {
                    return text
                }
                if item["type"] as? String == "tool_use",
                   let name = item["name"] as? String {
                    return "🔧 Using tool: \(name)"
                }
                return nil
            }
            if !texts.isEmpty {
                return texts.joined(separator: "\n")
            }
        }

        // Try to get result from success messages
        if let result = message["result"]?.value as? String {
            return result
        }

        // Try subtype for system messages
        if let subtype = message["subtype"]?.value as? String {
            switch subtype {
            case "init":
                return nil  // Filtered out in displayableEvents
            case "success":
                return nil  // Don't show completion messages, the response is enough
            default:
                return nil
            }
        }

        // Fallback: show message type if available
        if let type = message["type"]?.value as? String {
            return "[\(type)]"
        }

        return nil
    }
}

struct PermissionCardView: View {
    @Environment(AppState.self) private var appState
    let session: Session
    let permission: PermissionRequestMessage

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Image(systemName: "exclamationmark.shield")
                    .foregroundStyle(.orange)
                Text("Permission Required")
                    .font(.headline)
                Spacer()
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("Tool: \(permission.toolName)")
                    .font(.subheadline)
                    .fontWeight(.medium)

                // Show relevant input details
                ForEach(Array(permission.toolInput.keys.sorted().prefix(3)), id: \.self) { key in
                    if let value = permission.toolInput[key]?.value {
                        Text("\(key): \(String(describing: value).prefix(100))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }

            HStack(spacing: 16) {
                Button {
                    Task {
                        await appState.sendPermissionResponse(
                            requestId: permission.requestId,
                            decision: .deny
                        )
                    }
                } label: {
                    Text("Deny")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)

                Button {
                    Task {
                        await appState.sendPermissionResponse(
                            requestId: permission.requestId,
                            decision: .allow
                        )
                    }
                } label: {
                    Text("Allow")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .background(.ultraThinMaterial)
    }
}

struct InputBarView: View {
    @Environment(AppState.self) private var appState
    let session: Session
    @State private var inputText = ""

    var body: some View {
        HStack(spacing: 12) {
            TextField("Send a message...", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .padding(10)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20))
                .lineLimit(1...5)
                .onSubmit {
                    sendMessage()
                }
                .submitLabel(.send)

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
            }
            .disabled(inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding()
        .background(.bar)
    }

    func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        Task {
            await appState.sendInput(session: session.name, text: text)
            inputText = ""
        }
    }
}

#Preview {
    NavigationStack {
        SessionDetailView(session: Session(
            name: "myproject-abc1",
            directory: "/Users/dev/myproject",
            state: .working,
            costUsd: 0.0234
        ))
    }
    .environment(AppState())
}
