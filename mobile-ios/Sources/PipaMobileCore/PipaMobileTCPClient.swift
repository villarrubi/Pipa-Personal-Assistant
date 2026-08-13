import Foundation
import Network

private final class PipaAsyncGate: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !completed else { return false }
        completed = true
        return true
    }
}

public struct PipaMobileCatalog {
    public let commands: [[String: Any]]
    public let capabilities: [String: [String: Any]]

    public init(commands: [[String: Any]], capabilities: [String: [String: Any]] = [:]) {
        self.commands = commands
        self.capabilities = capabilities
    }
}

@available(iOS 16.0, *)
public actor PipaMobileTCPClient {
    private let identity: PipaMobileIdentity
    private let serverPublicKeyData: Data
    private let serverID: String
    private let firmwareVersion: String
    private let capabilities: [String]
    private let queue = DispatchQueue(label: "com.pipa.mobile.tcp")
    private static let connectionTimeout: DispatchTimeInterval = .seconds(10)
    private static let ioTimeout: DispatchTimeInterval = .seconds(15)
    private static let maxArgumentsBytes = 4096

    private var connection: NWConnection?
    private var recordLayer: PipaSecureRecordLayer?
    private var receiveBuffer = Data()
    private var requestInFlight = false

    public init(
        identity: PipaMobileIdentity,
        serverPublicKeyData: Data,
        serverID: String,
        firmwareVersion: String = "pipa-ios",
        capabilities: [String] = ["display", "touch", "mobile", "text_input"]
    ) throws {
        guard serverPublicKeyData.count == 32,
              PipaMobileIdentity.isValidIdentifier(serverID),
              !firmwareVersion.isEmpty,
              firmwareVersion.utf8.count <= 32,
              !capabilities.isEmpty,
              capabilities.count <= 16,
              Set(capabilities).count == capabilities.count,
              capabilities.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 32 }) else {
            throw PipaMobileError.invalidIdentity
        }
        self.identity = identity
        self.serverPublicKeyData = serverPublicKeyData
        self.serverID = serverID
        self.firmwareVersion = firmwareVersion
        self.capabilities = capabilities
    }

    public var isConnected: Bool {
        connection != nil && recordLayer != nil
    }

    public func connect(host: String, port: UInt16) async throws {
        guard !host.isEmpty,
              host.utf8.count <= 253,
              Self.isAllowedHost(host),
              port != 0,
              connection == nil else {
            throw PipaMobileError.transportUnavailable
        }
        let endpoint = NWEndpoint.Host(host)
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            throw PipaMobileError.transportUnavailable
        }
        let newConnection = NWConnection(host: endpoint, port: nwPort, using: .tcp)
        connection = newConnection
        receiveBuffer.removeAll(keepingCapacity: true)
        do {
            try await start(newConnection)
            let context = try PipaMobileHandshake.makeClientHello(identity: identity)
            try await sendJSONObject(context.hello)
            guard let serverHello = try await receiveJSONObject() else {
                throw PipaMobileError.invalidHandshake
            }
            recordLayer = try PipaMobileHandshake.complete(
                context: context,
                serverHello: serverHello,
                serverPublicKeyData: serverPublicKeyData,
                expectedServerID: serverID
            )
            let responses = try await send(
                type: "device_hello",
                fields: [
                    "firmware_version": firmwareVersion,
                    "capabilities": capabilities,
                ],
                expectsUIState: false
            )
            guard responses.count == 1, responses[0]["type"] as? String == "device_hello_ack" else {
                throw PipaMobileError.invalidHandshake
            }
        } catch {
            disconnect()
            throw error
        }
    }

    // Keep the mobile endpoint aligned with the Windows gateway policy: no
    // DNS names, wildcard binds, public addresses, or port-forwarded hosts.
    // IPv6 link-local/ULA support can be added once the app has a scoped
    // interface model; the current product contract provisions a canonical
    // literal IPv4 (no alternate/legacy octet spellings).
    static func isAllowedHost(_ host: String) -> Bool {
        guard host == host.trimmingCharacters(in: .whitespacesAndNewlines) else {
            return false
        }
        if host == "::1" {
            return true
        }
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4,
              parts.allSatisfy({
                  !$0.isEmpty &&
                      ($0.count == 1 || $0.first != "0") &&
                      $0.unicodeScalars.allSatisfy { scalar in
                          scalar.value >= 0x30 && scalar.value <= 0x39
                      }
              }) else {
            return false
        }
        let octets = parts.compactMap { Int($0) }
        guard octets.count == 4,
              octets.allSatisfy({ $0 >= 0 && $0 <= 255 }) else {
            return false
        }
        let first = octets[0]
        let second = octets[1]
        return first == 10 ||
            first == 127 ||
            (first == 172 && second >= 16 && second <= 31) ||
            (first == 192 && second == 168) ||
            (first == 169 && second == 254)
    }

    public func disconnect() {
        recordLayer?.close()
        recordLayer = nil
        connection?.cancel()
        connection = nil
        receiveBuffer.removeAll(keepingCapacity: false)
        requestInFlight = false
    }

    public func sendText(_ text: String) async throws -> [[String: Any]] {
        guard !text.isEmpty,
              text.utf8.count <= 4000,
              !Self.containsProtocolControl(text),
              !PipaMobileTextPolicy.containsDisplayControl(text) else {
            throw PipaMobileError.invalidMessage
        }
        return try await send(
            type: "text_input",
            fields: ["text": text, "source": "mobile"],
            expectsUIState: true
        )
    }

    public func requestCatalog() async throws -> [[String: Any]] {
        let details = try await requestCatalogDetails()
        return details.commands
    }

    public func requestCatalogDetails() async throws -> PipaMobileCatalog {
        let responses = try await send(type: "catalog_request", fields: [:], expectsUIState: false)
        guard responses.count == 1,
              responses[0]["type"] as? String == "catalog",
              let commands = responses[0]["commands"] as? [[String: Any]],
              commands.count <= 64 else {
            throw PipaMobileError.invalidMessage
        }
        let capabilities = try Self.parseCapabilities(responses[0]["capabilities"])
        return PipaMobileCatalog(commands: commands, capabilities: capabilities)
    }

    public func callTool(
        name: String,
        arguments: [String: Any] = [:],
        callID: String? = nil
    ) async throws -> [[String: Any]] {
        guard !name.isEmpty,
              name.utf8.count <= 80,
              !Self.containsProtocolControl(name),
              !PipaMobileTextPolicy.containsDisplayControl(name),
              JSONSerialization.isValidJSONObject(arguments),
              let encodedArguments = try? JSONSerialization.data(
                  withJSONObject: arguments,
                  options: [.sortedKeys, .withoutEscapingSlashes]
              ) else {
            throw PipaMobileError.invalidMessage
        }
        guard encodedArguments.count <= Self.maxArgumentsBytes else {
            throw PipaMobileError.payloadTooLarge
        }
        var fields: [String: Any] = ["name": name, "arguments": arguments]
        if let callID {
            guard !callID.isEmpty,
                  callID.utf8.count <= 128,
                  !Self.containsProtocolControl(callID),
                  !PipaMobileTextPolicy.containsDisplayControl(callID) else {
                throw PipaMobileError.invalidMessage
            }
            fields["call_id"] = callID
        }
        return try await send(type: "tool_call", fields: fields, expectsUIState: true)
    }

    public func confirm(confirmationID: String, accepted: Bool) async throws -> [[String: Any]] {
        guard !confirmationID.isEmpty,
              confirmationID.utf8.count <= 128,
              !Self.containsProtocolControl(confirmationID),
              !PipaMobileTextPolicy.containsDisplayControl(confirmationID) else {
            throw PipaMobileError.invalidMessage
        }
        return try await send(
            type: "confirm",
            fields: ["confirmation_id": confirmationID, "accepted": accepted],
            expectsUIState: true
        )
    }

    private func start(_ connection: NWConnection) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = PipaAsyncGate()
            let timeout = DispatchWorkItem {
                guard gate.claim() else { return }
                connection.cancel()
                continuation.resume(throwing: PipaMobileError.transportUnavailable)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    guard gate.claim() else { return }
                    timeout.cancel()
                    continuation.resume()
                case .failed(_), .cancelled:
                    guard gate.claim() else { return }
                    timeout.cancel()
                    continuation.resume(throwing: PipaMobileError.transportUnavailable)
                default:
                    break
                }
            }
            connection.start(queue: queue)
            queue.asyncAfter(deadline: .now() + Self.connectionTimeout, execute: timeout)
        }
    }

    private static func containsProtocolControl(_ value: String) -> Bool {
        PipaMobileTextPolicy.containsProtocolControl(value)
    }

    private static func parseCapabilities(_ value: Any?) throws -> [String: [String: Any]] {
        guard let value else { return [:] }
        guard let groups = value as? [String: Any], groups.count <= 16 else {
            throw PipaMobileError.invalidMessage
        }

        var parsed: [String: [String: Any]] = [:]
        for (groupID, rawFields) in groups {
            guard capabilityGroups.contains(groupID),
                  let fields = rawFields as? [String: Any],
                  fields.count <= 16 else {
                throw PipaMobileError.invalidMessage
            }
            var safeFields: [String: Any] = [:]
            for (fieldName, fieldValue) in fields {
                guard isCatalogKey(fieldName), isCapabilityValue(fieldValue, fieldName: fieldName) else {
                    throw PipaMobileError.invalidMessage
                }
                safeFields[fieldName] = fieldValue
            }
            parsed[groupID] = safeFields
        }
        return parsed
    }

    private static let capabilityGroups: Set<String> = [
        "web_search", "apple_music", "whatsapp", "discord", "league", "codex",
    ]

    private static let booleanCapabilityFields: Set<String> = [
        "available", "app_configured", "search", "playback", "media_control", "requires_manual_selection",
        "open_web", "open_contact", "prepare_message", "send_message", "requires_manual_send",
        "open_app", "open_channel", "start_call", "requires_manual_call", "client_ready",
        "open_client", "matchmaking", "cancel_matchmaking", "accept_match", "requires_manual_accept",
        "writes_to_chat", "requires_confirmation",
    ]

    private static let stringCapabilityFields: Set<String> = ["execution"]
    private static let listCapabilityFields: Set<String> = ["queues"]

    private static func isCatalogKey(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 64 else { return false }
        return value.utf8.allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5A) ||
                (byte >= 0x61 && byte <= 0x7A) ||
                (byte >= 0x30 && byte <= 0x39) ||
                byte == 0x2D || byte == 0x5F
        }
    }

    private static func isCapabilityValue(_ value: Any, fieldName: String) -> Bool {
        if value is Bool { return booleanCapabilityFields.contains(fieldName) }
        if let text = value as? String {
            return stringCapabilityFields.contains(fieldName) &&
                !text.isEmpty &&
                text.utf8.count <= 128 &&
                !containsProtocolControl(text)
        }
        if let list = value as? [String] {
            return listCapabilityFields.contains(fieldName) &&
                list.count <= 16 &&
                list.allSatisfy {
                    !$0.isEmpty &&
                        $0.utf8.count <= 128 &&
                        !containsProtocolControl($0)
                }
        }
        return false
    }

    private func send(
        type: String,
        fields: [String: Any],
        expectsUIState: Bool
    ) async throws -> [[String: Any]] {
        guard !requestInFlight else { throw PipaMobileError.requestInProgress }
        requestInFlight = true
        defer { requestInFlight = false }
        do {
            guard recordLayer != nil else { throw PipaMobileError.sessionClosed }
            var payload = fields
            payload["protocol_version"] = 1
            payload["type"] = type
            guard let layer = recordLayer else { throw PipaMobileError.sessionClosed }
            try await sendJSONObject(layer.seal(payload: payload))
            guard let first = try await receiveEncrypted() else {
                throw PipaMobileError.transportUnavailable
            }
            var responses = [first]
            if expectsUIState {
                guard let followUp = try await receiveEncrypted(),
                      followUp["type"] as? String == "ui_state" else {
                    throw PipaMobileError.invalidMessage
                }
                responses.append(followUp)
            }
            return responses
        } catch {
            // A failed request may have consumed an authenticated record or
            // left the framing state uncertain. Require a fresh handshake.
            disconnect()
            throw error
        }
    }

    private func receiveEncrypted() async throws -> [String: Any]? {
        guard let frame = try await receiveJSONObject(), let layer = recordLayer else {
            return nil
        }
        return try layer.open(frame: frame)
    }

    private func sendJSONObject(_ object: [String: Any]) async throws {
        guard let connection else { throw PipaMobileError.transportUnavailable }
        let data: Data
        do {
            data = try JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
            ) + Data([0x0A])
        } catch {
            throw PipaMobileError.invalidMessage
        }
        guard data.count <= PipaSecureRecordLayer.maxFrameBytes else {
            throw PipaMobileError.payloadTooLarge
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = PipaAsyncGate()
            connection.send(content: data, completion: .contentProcessed { error in
                guard gate.claim() else { return }
                if error == nil {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: PipaMobileError.transportUnavailable)
                }
            })
            queue.asyncAfter(deadline: .now() + Self.ioTimeout) {
                guard gate.claim() else { return }
                connection.cancel()
                continuation.resume(throwing: PipaMobileError.transportUnavailable)
            }
        }
    }

    private func receiveJSONObject() async throws -> [String: Any]? {
        while true {
            if let newline = receiveBuffer.firstIndex(of: 0x0A) {
                let line = receiveBuffer.subdata(in: receiveBuffer.startIndex..<newline)
                receiveBuffer.removeSubrange(receiveBuffer.startIndex..<(newline + 1))
                guard !line.isEmpty, line.count <= PipaSecureRecordLayer.maxFrameBytes else {
                    throw PipaMobileError.invalidMessage
                }
                guard PipaMobileCodec.isStrictJSONObject(line) else {
                    throw PipaMobileError.invalidMessage
                }
                guard let object = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                    throw PipaMobileError.invalidMessage
                }
                return object
            }

            guard receiveBuffer.count < PipaSecureRecordLayer.maxFrameBytes else {
                throw PipaMobileError.payloadTooLarge
            }
            guard let connection else { throw PipaMobileError.transportUnavailable }
            let remaining = PipaSecureRecordLayer.maxFrameBytes - receiveBuffer.count
            let (chunk, isComplete) = try await receiveChunk(connection, maximumLength: remaining)
            if let chunk, !chunk.isEmpty {
                receiveBuffer.append(chunk)
            } else if !isComplete {
                throw PipaMobileError.transportUnavailable
            }
            if isComplete {
                if receiveBuffer.firstIndex(of: 0x0A) != nil {
                    continue
                }
                return nil
            }
        }
    }

    private func receiveChunk(_ connection: NWConnection, maximumLength: Int) async throws -> (Data?, Bool) {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<(Data?, Bool), Error>) in
            let gate = PipaAsyncGate()
            connection.receive(
                minimumIncompleteLength: 1,
                maximumLength: maximumLength
            ) { data, _, isComplete, error in
                guard gate.claim() else { return }
                if error != nil {
                    continuation.resume(throwing: PipaMobileError.transportUnavailable)
                } else {
                    continuation.resume(returning: (data, isComplete))
                }
            }
            queue.asyncAfter(deadline: .now() + Self.ioTimeout) {
                guard gate.claim() else { return }
                connection.cancel()
                continuation.resume(throwing: PipaMobileError.transportUnavailable)
            }
        }
    }
}
