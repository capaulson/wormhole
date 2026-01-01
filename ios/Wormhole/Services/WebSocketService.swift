import Foundation

/// WebSocket service for communicating with Wormhole daemon
final class WebSocketService: @unchecked Sendable {
    private let host: String
    private let port: Int
    private var webSocket: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private var isConnecting = false
    private var shouldReconnect = true
    private var reconnectAttempt = 0
    private let maxReconnectAttempts = 10

    var onMessage: ((ServerMessage) -> Void)?
    var onConnectionChange: ((Bool, String?) -> Void)?

    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        // Pydantic sends ISO8601 with fractional seconds but no timezone
        // e.g., "2025-12-31T23:46:22.733940"
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            // Try with fractional seconds first
            if let date = formatter.date(from: dateString) {
                return date
            }

            // Fall back to without fractional seconds
            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
                return date
            }

            // Try adding Z if no timezone
            if !dateString.hasSuffix("Z") && !dateString.contains("+") {
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                if let date = formatter.date(from: dateString + "Z") {
                    return date
                }
                formatter.formatOptions = [.withInternetDateTime]
                if let date = formatter.date(from: dateString + "Z") {
                    return date
                }
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
        return decoder
    }()

    init(host: String, port: Int) {
        self.host = host
        self.port = port
    }

    func connect() async {
        guard !isConnecting else { return }
        isConnecting = true
        shouldReconnect = true
        reconnectAttempt = 0

        await performConnect()
    }

    private func performConnect() async {
        guard let url = URL(string: "ws://\(host):\(port)") else {
            onConnectionChange?(false, "Invalid URL")
            return
        }

        urlSession = URLSession(configuration: .default)
        webSocket = urlSession?.webSocketTask(with: url)
        webSocket?.resume()

        // Send hello message
        await sendHello()

        // Start receiving messages
        receiveMessages()

        isConnecting = false
        reconnectAttempt = 0
        onConnectionChange?(true, nil)
    }

    func disconnect() {
        shouldReconnect = false
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        urlSession?.invalidateAndCancel()
        urlSession = nil
        onConnectionChange?(false, nil)
    }

    func send<T: Encodable>(_ message: T) async {
        guard let webSocket = webSocket else { return }

        do {
            let data = try encoder.encode(message)
            if let string = String(data: data, encoding: .utf8) {
                try await webSocket.send(.string(string))
            }
        } catch {
            print("Failed to send message: \(error)")
        }
    }

    private func sendHello() async {
        let deviceName = await MainActor.run { UIDevice.current.name }
        let hello = HelloMessage(
            clientVersion: "1.0.0",
            deviceName: deviceName
        )
        await send(hello)

        // Subscribe to all sessions
        let subscribe = SubscribeMessage(sessions: .all)
        await send(subscribe)
    }

    private func receiveMessages() {
        webSocket?.receive { [weak self] result in
            guard let self = self else { return }

            switch result {
            case .success(let message):
                self.handleMessage(message)
                self.receiveMessages()

            case .failure(let error):
                print("WebSocket receive error: \(error)")
                self.handleDisconnection(error: error.localizedDescription)
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            print("[WS] Received: \(text.prefix(200))...")
            guard let data = text.data(using: .utf8) else { return }
            do {
                let serverMessage = try decoder.decode(ServerMessage.self, from: data)
                print("[WS] Decoded: \(serverMessage)")
                onMessage?(serverMessage)
            } catch {
                print("[WS] Failed to decode message: \(error)")
                print("[WS] Raw message was: \(text)")
            }

        case .data(let data):
            print("[WS] Received binary data: \(data.count) bytes")
            do {
                let serverMessage = try decoder.decode(ServerMessage.self, from: data)
                onMessage?(serverMessage)
            } catch {
                print("[WS] Failed to decode binary message: \(error)")
            }

        @unknown default:
            break
        }
    }

    private func handleDisconnection(error: String?) {
        webSocket = nil
        onConnectionChange?(false, error)

        guard shouldReconnect, reconnectAttempt < maxReconnectAttempts else {
            return
        }

        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
        let delay = min(pow(2.0, Double(reconnectAttempt)), 60.0)
        reconnectAttempt += 1

        Task {
            try? await Task.sleep(for: .seconds(delay))

            if shouldReconnect {
                await performConnect()
            }
        }
    }
}

import UIKit // For UIDevice.current.name
