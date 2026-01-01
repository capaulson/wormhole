import XCTest
@testable import Wormhole

final class MachineTests: XCTestCase {

    func testConnectionURL() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117
        )

        XCTAssertEqual(machine.connectionURL?.absoluteString, "ws://192.168.1.100:7117")
    }

    func testDisplayNameManual() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117,
            isManual: true
        )

        XCTAssertEqual(machine.displayName, "Test Mac (manual)")
    }

    func testDisplayNameDiscovered() {
        let machine = Machine(
            id: "test",
            name: "Test Mac",
            host: "192.168.1.100",
            port: 7117,
            isManual: false
        )

        XCTAssertEqual(machine.displayName, "Test Mac")
    }
}

final class SessionTests: XCTestCase {

    func testStateDisplayName() {
        XCTAssertEqual(SessionState.idle.displayName, "Idle")
        XCTAssertEqual(SessionState.working.displayName, "Working")
        XCTAssertEqual(SessionState.awaitingApproval.displayName, "Awaiting Approval")
        XCTAssertEqual(SessionState.error.displayName, "Error")
    }

    func testStateBadgeColor() {
        XCTAssertEqual(SessionState.idle.badgeColor, "blue")
        XCTAssertEqual(SessionState.working.badgeColor, "yellow")
        XCTAssertEqual(SessionState.awaitingApproval.badgeColor, "purple")
        XCTAssertEqual(SessionState.error.badgeColor, "red")
    }

    func testInitFromSessionInfo() {
        let info = SessionInfo(
            name: "test-abc1",
            directory: "/Users/test/project",
            state: "working",
            claudeSessionId: "session-123",
            costUsd: 0.05,
            lastActivity: Date()
        )

        let session = Session(from: info)

        XCTAssertEqual(session.name, "test-abc1")
        XCTAssertEqual(session.directory, "/Users/test/project")
        XCTAssertEqual(session.state, .working)
        XCTAssertEqual(session.claudeSessionId, "session-123")
        XCTAssertEqual(session.costUsd, 0.05)
    }

    func testUnknownState() {
        let info = SessionInfo(
            name: "test",
            directory: "/tmp",
            state: "unknown_state",
            claudeSessionId: nil,
            costUsd: 0,
            lastActivity: Date()
        )

        let session = Session(from: info)

        // Should default to idle for unknown states
        XCTAssertEqual(session.state, .idle)
    }
}

final class SessionStateCodableTests: XCTestCase {

    func testEncoding() throws {
        let encoder = JSONEncoder()

        let idleData = try encoder.encode(SessionState.idle)
        XCTAssertEqual(String(data: idleData, encoding: .utf8), "\"idle\"")

        let awaitingData = try encoder.encode(SessionState.awaitingApproval)
        XCTAssertEqual(String(data: awaitingData, encoding: .utf8), "\"awaiting_approval\"")
    }

    func testDecoding() throws {
        let decoder = JSONDecoder()

        let idle = try decoder.decode(SessionState.self, from: "\"idle\"".data(using: .utf8)!)
        XCTAssertEqual(idle, .idle)

        let awaiting = try decoder.decode(SessionState.self, from: "\"awaiting_approval\"".data(using: .utf8)!)
        XCTAssertEqual(awaiting, .awaitingApproval)
    }
}
