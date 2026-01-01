import SwiftUI

struct SessionRowView: View {
    let session: Session

    var body: some View {
        HStack(spacing: 12) {
            StateBadge(state: session.state)

            VStack(alignment: .leading, spacing: 4) {
                Text(session.name)
                    .font(.headline)

                Text(session.directory)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer()
        }
        .padding(.vertical, 4)
    }
}

struct StateBadge: View {
    let state: SessionState

    var body: some View {
        Text(state.displayName)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(backgroundColor)
            .foregroundStyle(.white)
            .clipShape(Capsule())
    }

    var backgroundColor: Color {
        switch state {
        case .idle: return .blue
        case .working: return .orange
        case .awaitingApproval: return .purple
        case .error: return .red
        }
    }
}

#Preview {
    List {
        SessionRowView(session: Session(
            name: "myproject-abc1",
            directory: "/Users/dev/myproject",
            state: .idle,
            costUsd: 0.0234
        ))

        SessionRowView(session: Session(
            name: "webapp-xyz9",
            directory: "/Users/dev/webapp",
            state: .working
        ))

        SessionRowView(session: Session(
            name: "api-server-1234",
            directory: "/Users/dev/api-server",
            state: .awaitingApproval
        ))

        SessionRowView(session: Session(
            name: "broken-session",
            directory: "/Users/dev/broken",
            state: .error
        ))
    }
}
