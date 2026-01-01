import XCTest
@testable import Wormhole

final class ProtocolTests: XCTestCase {

    func testHelloMessageEncoding() throws {
        let hello = HelloMessage(clientVersion: "1.0.0", deviceName: "Test iPhone")
        let encoder = JSONEncoder()
        let data = try encoder.encode(hello)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "hello")
        XCTAssertEqual(json["client_version"] as? String, "1.0.0")
        XCTAssertEqual(json["device_name"] as? String, "Test iPhone")
    }

    func testInputMessageEncoding() throws {
        let input = InputMessage(session: "test-session", text: "Hello Claude")
        let encoder = JSONEncoder()
        let data = try encoder.encode(input)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "input")
        XCTAssertEqual(json["session"] as? String, "test-session")
        XCTAssertEqual(json["text"] as? String, "Hello Claude")
    }

    func testPermissionResponseEncoding() throws {
        let response = PermissionResponseMessage(
            requestId: "req-123",
            decision: .allow
        )
        let encoder = JSONEncoder()
        let data = try encoder.encode(response)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "permission_response")
        XCTAssertEqual(json["request_id"] as? String, "req-123")
        XCTAssertEqual(json["decision"] as? String, "allow")
    }

    func testControlMessageEncoding() throws {
        let control = ControlMessage(session: "test-session", action: .interrupt)
        let encoder = JSONEncoder()
        let data = try encoder.encode(control)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "control")
        XCTAssertEqual(json["session"] as? String, "test-session")
        XCTAssertEqual(json["action"] as? String, "interrupt")
    }

    func testSyncMessageEncoding() throws {
        let sync = SyncMessage(session: "test-session", lastSeenSequence: 42)
        let encoder = JSONEncoder()
        let data = try encoder.encode(sync)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "sync")
        XCTAssertEqual(json["session"] as? String, "test-session")
        XCTAssertEqual(json["last_seen_sequence"] as? Int, 42)
    }

    func testWelcomeMessageDecoding() throws {
        let json = """
        {
            "type": "welcome",
            "server_version": "0.1.0",
            "machine_name": "Test Mac",
            "sessions": [
                {
                    "name": "project-abc1",
                    "directory": "/Users/test/project",
                    "state": "idle",
                    "claude_session_id": null,
                    "cost_usd": 0.0234,
                    "last_activity": "2025-12-31T10:30:00Z"
                }
            ]
        }
        """

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let data = json.data(using: .utf8)!
        let message = try decoder.decode(ServerMessage.self, from: data)

        guard case .welcome(let welcome) = message else {
            XCTFail("Expected welcome message")
            return
        }

        XCTAssertEqual(welcome.serverVersion, "0.1.0")
        XCTAssertEqual(welcome.machineName, "Test Mac")
        XCTAssertEqual(welcome.sessions.count, 1)
        XCTAssertEqual(welcome.sessions[0].name, "project-abc1")
        XCTAssertEqual(welcome.sessions[0].state, "idle")
    }

    func testPermissionRequestDecoding() throws {
        let json = """
        {
            "type": "permission_request",
            "request_id": "req-456",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test.txt",
                "content": "Hello World"
            },
            "session_name": "project-abc1"
        }
        """

        let decoder = JSONDecoder()
        let data = json.data(using: .utf8)!
        let message = try decoder.decode(ServerMessage.self, from: data)

        guard case .permissionRequest(let request) = message else {
            XCTFail("Expected permission request message")
            return
        }

        XCTAssertEqual(request.requestId, "req-456")
        XCTAssertEqual(request.toolName, "Write")
        XCTAssertEqual(request.sessionName, "project-abc1")
    }

    func testErrorMessageDecoding() throws {
        let json = """
        {
            "type": "error",
            "code": "SESSION_NOT_FOUND",
            "message": "Session not found: test-session",
            "session": null
        }
        """

        let decoder = JSONDecoder()
        let data = json.data(using: .utf8)!
        let message = try decoder.decode(ServerMessage.self, from: data)

        guard case .error(let error) = message else {
            XCTFail("Expected error message")
            return
        }

        XCTAssertEqual(error.code, "SESSION_NOT_FOUND")
        XCTAssertEqual(error.message, "Session not found: test-session")
    }
}
