import Foundation
import Testing
@testable import Wormhole

// MARK: - Machine Tests

@Suite("Machine Tests")
struct MachineTests {

    @Test("Connection URL generation")
    func connectionURL() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117
        )

        #expect(machine.connectionURL?.absoluteString == "ws://192.168.1.100:7117")
    }

    @Test("Display name for manual machine")
    func displayNameManual() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117,
            isManual: true
        )

        #expect(machine.displayName == "Test Mac (manual)")
    }

    @Test("Display name for discovered machine")
    func displayNameDiscovered() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117,
            isManual: false
        )

        #expect(machine.displayName == "Test Mac")
    }
}

// MARK: - Session State Tests

@Suite("Session State Tests")
struct SessionStateTests {

    @Test("State display names")
    func stateDisplayName() {
        #expect(SessionState.idle.displayName == "Idle")
        #expect(SessionState.working.displayName == "Working")
        #expect(SessionState.awaitingApproval.displayName == "Awaiting Approval")
        #expect(SessionState.error.displayName == "Error")
    }

    @Test("State badge colors")
    func stateBadgeColor() {
        #expect(SessionState.idle.badgeColor == "blue")
        #expect(SessionState.working.badgeColor == "yellow")
        #expect(SessionState.awaitingApproval.badgeColor == "purple")
        #expect(SessionState.error.badgeColor == "red")
    }
}

// MARK: - Session Tests

@Suite("Session Tests")
struct SessionTests {

    @Test("Init from SessionInfo")
    func initFromSessionInfo() {
        let info = SessionInfo(
            name: "test-abc1",
            directory: "/Users/test/project",
            state: "working",
            claudeSessionId: "session-123",
            costUsd: 0.05,
            lastActivity: Date()
        )

        let session = Session(from: info, machineId: "mac1", machineName: "Test Mac")

        #expect(session.name == "test-abc1")
        #expect(session.directory == "/Users/test/project")
        #expect(session.state == .working)
        #expect(session.claudeSessionId == "session-123")
        #expect(session.costUsd == 0.05)
        #expect(session.machineId == "mac1")
        #expect(session.machineName == "Test Mac")
    }

    @Test("Unknown state defaults to idle")
    func unknownState() {
        let info = SessionInfo(
            name: "test",
            directory: "/tmp",
            state: "unknown_state",
            claudeSessionId: nil,
            costUsd: 0,
            lastActivity: Date()
        )

        let session = Session(from: info, machineId: "mac1", machineName: "Test Mac")

        // Should default to idle for unknown states
        #expect(session.state == .idle)
    }

    @Test("Session ID is compound of machineId and name")
    func sessionIdIsCompound() {
        let session = Session(
            name: "test-session",
            directory: "/tmp",
            machineId: "mac1",
            machineName: "Test Mac"
        )

        #expect(session.id == "mac1:test-session")
    }
}

// MARK: - Session State Codable Tests

@Suite("Session State Codable Tests")
struct SessionStateCodableTests {

    @Test("Encoding session states")
    func encoding() throws {
        let encoder = JSONEncoder()

        let idleData = try encoder.encode(SessionState.idle)
        #expect(String(data: idleData, encoding: .utf8) == "\"idle\"")

        let awaitingData = try encoder.encode(SessionState.awaitingApproval)
        #expect(String(data: awaitingData, encoding: .utf8) == "\"awaiting_approval\"")
    }

    @Test("Decoding session states")
    func decoding() throws {
        let decoder = JSONDecoder()

        let idle = try decoder.decode(SessionState.self, from: "\"idle\"".data(using: .utf8)!)
        #expect(idle == .idle)

        let awaiting = try decoder.decode(SessionState.self, from: "\"awaiting_approval\"".data(using: .utf8)!)
        #expect(awaiting == .awaitingApproval)
    }
}
