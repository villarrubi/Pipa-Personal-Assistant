import CryptoKit
import Foundation

public enum PipaMobileError: Error {
    case invalidIdentity
    case invalidMessage
    case invalidBase64
    case invalidHandshake
    case invalidRecord
    case replay
    case sessionClosed
    case payloadTooLarge
    case transportUnavailable
    case requestInProgress
}

/// Shared bounds for text crossing the mobile UI or line-based protocol.
///
/// The Windows Core rejects protocol controls. The mobile side also rejects
/// common bidirectional and zero-width formatting controls so an untrusted
/// catalog or caption cannot visually disguise the action being approved.
public enum PipaMobileTextPolicy {
    public static func containsProtocolControl(_ value: String) -> Bool {
        value.unicodeScalars.contains { scalar in
            scalar.value < 0x20 || scalar.value == 0x7F
        }
    }

    public static func containsDisplayControl(_ value: String) -> Bool {
        value.unicodeScalars.contains { scalar in
            let codePoint = scalar.value
            return codePoint < 0x20 ||
                (0x7F...0x9F).contains(codePoint) ||
                (0x200B...0x200F).contains(codePoint) ||
                (0x202A...0x202E).contains(codePoint) ||
                (0x2060...0x2069).contains(codePoint) ||
                codePoint == 0xFEFF
        }
    }

    public static func isSafeDisplayText(_ value: String, maxBytes: Int) -> Bool {
        !value.isEmpty && value.utf8.count <= maxBytes && !containsDisplayControl(value)
    }
}

public struct PipaMobileIdentity {
    public let identityID: String
    // Internal by design: callers use Keychain/generate and can inspect only
    // the public key and fingerprint. The private key never belongs to the
    // public package API.
    let privateKey: Curve25519.Signing.PrivateKey

    init(identityID: String, privateKey: Curve25519.Signing.PrivateKey) throws {
        guard Self.isValidIdentifier(identityID) else {
            throw PipaMobileError.invalidIdentity
        }
        self.identityID = identityID
        self.privateKey = privateKey
    }

    public static func generate(identityID: String) throws -> PipaMobileIdentity {
        try PipaMobileIdentity(identityID: identityID, privateKey: .init())
    }

    public var publicKeyData: Data {
        privateKey.publicKey.rawRepresentation
    }

    public var publicKeyBase64URL: String {
        PipaMobileCodec.encodeBase64URL(publicKeyData)
    }

    public static func decodePublicKeyBase64URL(_ value: String) throws -> Data {
        let data = try PipaMobileCodec.decodeBase64URL(value, expectedCount: 32)
        return data
    }

    public var fingerprint: String {
        Self.publicKeyDigest(forPublicKeyData: publicKeyData)!
    }

    /// Return the out-of-band fingerprint for a pinned Ed25519 public key.
    /// Private key material is neither accepted nor needed here.
    public static func publicKeyDigest(forPublicKeyData data: Data) -> String? {
        guard data.count == 32 else { return nil }
        return SHA256.hash(data: data)
            .map { String(format: "%02X", $0) }
            .joined(separator: ":")
    }

    fileprivate func sign(_ data: Data) throws -> Data {
        try privateKey.signature(for: data)
    }

    static func isValidIdentifier(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 128 else { return false }
        return value.utf8.allSatisfy { byte in
            (byte >= 0x41 && byte <= 0x5A) ||
                (byte >= 0x61 && byte <= 0x7A) ||
                (byte >= 0x30 && byte <= 0x39) ||
                byte == 0x2D || byte == 0x5F
        }
    }
}

public struct PipaClientHelloContext {
    public let hello: [String: Any]
    fileprivate let identity: PipaMobileIdentity
    fileprivate let ephemeralPrivateKey: Curve25519.KeyAgreement.PrivateKey
}

public enum PipaMobileHandshake {
    public static func makeClientHello(
        identity: PipaMobileIdentity,
        sessionID: String? = nil
    ) throws -> PipaClientHelloContext {
        let resolvedSessionID = sessionID ?? PipaMobileCodec.encodeBase64URL(PipaMobileCodec.randomData(count: 16))
        guard PipaMobileIdentity.isValidIdentifier(resolvedSessionID) else {
            throw PipaMobileError.invalidHandshake
        }

        let ephemeral = Curve25519.KeyAgreement.PrivateKey()
        let unsigned: [String: Any] = [
            "client_ephemeral_public_key": PipaMobileCodec.encodeBase64URL(ephemeral.publicKey.rawRepresentation),
            "client_id": identity.identityID,
            "client_nonce": PipaMobileCodec.encodeBase64URL(PipaMobileCodec.randomData(count: 32)),
            "protocol_version": 2,
            "session_id": resolvedSessionID,
        ]
        var signed = unsigned
        signed["role"] = "client"
        let signature = try identity.sign(PipaMobileCodec.canonicalJSON(signed))
        var hello = unsigned
        hello["signature"] = PipaMobileCodec.encodeBase64URL(signature)
        return PipaClientHelloContext(
            hello: hello,
            identity: identity,
            ephemeralPrivateKey: ephemeral
        )
    }

    public static func complete(
        context: PipaClientHelloContext,
        serverHello: [String: Any],
        serverPublicKeyData: Data,
        expectedServerID: String
    ) throws -> PipaSecureRecordLayer {
        let expectedFields: Set<String> = [
            "client_ephemeral_public_key",
            "client_id",
            "client_nonce",
            "protocol_version",
            "server_ephemeral_public_key",
            "server_id",
            "server_nonce",
            "session_id",
            "signature",
        ]
        guard Set(serverHello.keys) == expectedFields,
              serverHello["protocol_version"] as? Int == 2,
              let sessionID = serverHello["session_id"] as? String,
              let clientID = serverHello["client_id"] as? String,
              let clientEphemeral = serverHello["client_ephemeral_public_key"] as? String,
              let clientNonce = serverHello["client_nonce"] as? String,
              let serverID = serverHello["server_id"] as? String,
              let serverEphemeral = serverHello["server_ephemeral_public_key"] as? String,
              let serverNonce = serverHello["server_nonce"] as? String,
              let signatureText = serverHello["signature"] as? String,
              sessionID == context.hello["session_id"] as? String,
              clientID == context.identity.identityID,
              clientEphemeral == context.hello["client_ephemeral_public_key"] as? String,
              clientNonce == context.hello["client_nonce"] as? String,
              serverID == expectedServerID,
              PipaMobileIdentity.isValidIdentifier(serverID),
              let serverEphemeralData = try? PipaMobileCodec.decodeBase64URL(serverEphemeral, expectedCount: 32),
              let serverNonceData = try? PipaMobileCodec.decodeBase64URL(serverNonce, expectedCount: 32),
              let signature = try? PipaMobileCodec.decodeBase64URL(signatureText, expectedCount: 64),
              serverPublicKeyData.count == 32 else {
            throw PipaMobileError.invalidHandshake
        }

        var transcript = serverHello
        transcript.removeValue(forKey: "signature")
        var signedTranscript = transcript
        signedTranscript["role"] = "server"
        do {
            let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: serverPublicKeyData)
            guard publicKey.isValidSignature(signature, for: PipaMobileCodec.canonicalJSON(signedTranscript)) else {
                throw PipaMobileError.invalidHandshake
            }
        } catch let error as PipaMobileError {
            throw error
        } catch {
            throw PipaMobileError.invalidHandshake
        }

        let transcriptHash = Data(SHA256.hash(data: PipaMobileCodec.canonicalJSON(transcript)))
        do {
            let serverKey = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: serverEphemeralData)
            let sharedSecret = try context.ephemeralPrivateKey.sharedSecretFromKeyAgreement(with: serverKey)
            return try PipaSecureRecordLayer(
                sessionID: sessionID,
                sharedSecret: sharedSecret,
                transcriptHash: transcriptHash,
                role: .client
            )
        } catch {
            throw PipaMobileError.invalidHandshake
        }
    }
}

public final class PipaSecureRecordLayer {
    public static let maxRecordBytes = 64 * 1024
    public static let maxFrameBytes = 96 * 1024

    private let sessionID: String
    private let sendKey: SymmetricKey
    private let receiveKey: SymmetricKey
    private let sendNoncePrefix: Data
    private let receiveNoncePrefix: Data
    private var sendSequence: UInt64 = 0
    private var receiveSequence: UInt64 = 0
    private var closed = false

    enum Role {
        case client
        case server
    }

    // Internal deterministic entry point used only by the cross-language
    // fixture. Production handshakes use the SharedSecret initializer below.
    init(
        sessionID: String,
        sharedSecretData: Data,
        transcriptHash: Data,
        role: Role
    ) throws {
        guard sharedSecretData.count == 32,
              sharedSecretData.contains(where: { $0 != 0 }),
              transcriptHash.count == 32 else {
            throw PipaMobileError.invalidHandshake
        }
        self.sessionID = sessionID
        let info = Data("pipa/secure-session/v2".utf8) + transcriptHash
        let materialKey = SymmetricKey(data: sharedSecretData).hkdfDerivedSymmetricKey(
            using: SHA256.self,
            salt: transcriptHash,
            sharedInfo: info,
            outputByteCount: 72
        )
        let material = materialKey.withUnsafeBytes { Data($0) }
        let clientKey = SymmetricKey(data: material.subdata(in: 0..<32))
        let serverKey = SymmetricKey(data: material.subdata(in: 32..<64))
        let clientPrefix = material.subdata(in: 64..<68)
        let serverPrefix = material.subdata(in: 68..<72)
        if role == .client {
            sendKey = clientKey
            receiveKey = serverKey
            sendNoncePrefix = clientPrefix
            receiveNoncePrefix = serverPrefix
        } else {
            sendKey = serverKey
            receiveKey = clientKey
            sendNoncePrefix = serverPrefix
            receiveNoncePrefix = clientPrefix
        }
    }

    convenience init(
        sessionID: String,
        sharedSecret: SharedSecret,
        transcriptHash: Data,
        role: Role
    ) throws {
        let secret = sharedSecret.withUnsafeBytes { Data($0) }
        try self.init(
            sessionID: sessionID,
            sharedSecretData: secret,
            transcriptHash: transcriptHash,
            role: role
        )
    }

    public func close() {
        closed = true
    }

    public func seal(payload: [String: Any]) throws -> [String: Any] {
        guard !closed else { throw PipaMobileError.sessionClosed }
        guard sendSequence < UInt64.max else { throw PipaMobileError.sessionClosed }
        let plaintext = try PipaMobileCodec.canonicalJSON(payload)
        guard plaintext.count <= Self.maxRecordBytes else { throw PipaMobileError.payloadTooLarge }
        let sequence = sendSequence
        let header: [String: Any] = [
            "protocol_version": 2,
            "sequence": sequence,
            "session_id": sessionID,
        ]
        let nonce = sendNoncePrefix + PipaMobileCodec.bigEndian(sequence)
        let aad = try PipaMobileCodec.canonicalJSON(header) + Data("pipa/json/v2".utf8)
        let sealed = try ChaChaPoly.seal(
            plaintext,
            using: sendKey,
            nonce: try ChaChaPoly.Nonce(data: nonce),
            authenticating: aad
        )
        sendSequence += 1
        return header.merging(
            ["ciphertext": PipaMobileCodec.encodeBase64URL(sealed.ciphertext + sealed.tag)],
            uniquingKeysWith: { _, new in new }
        )
    }

    public func open(frame: [String: Any]) throws -> [String: Any] {
        guard !closed else { throw PipaMobileError.sessionClosed }
        var opened = false
        defer {
            // A malformed, replayed, or unauthenticated record invalidates the
            // whole session. The caller must perform a fresh handshake instead
            // of attempting to continue with an ambiguous sequence state.
            if !opened {
                closed = true
            }
        }
        let sequence: UInt64
        if let unsigned = frame["sequence"] as? UInt64 {
            sequence = unsigned
        } else if let signed = frame["sequence"] as? Int,
                  signed >= 0,
                  let converted = UInt64(exactly: signed) {
            sequence = converted
        } else {
            throw PipaMobileError.invalidRecord
        }
        guard Set(frame.keys) == Set(["ciphertext", "protocol_version", "sequence", "session_id"]),
              frame["protocol_version"] as? Int == 2,
              frame["session_id"] as? String == sessionID,
              sequence == receiveSequence,
              sequence < UInt64.max,
              let ciphertextText = frame["ciphertext"] as? String else {
            throw PipaMobileError.invalidRecord
        }
        let ciphertext = try PipaMobileCodec.decodeBase64URL(ciphertextText)
        guard ciphertext.count >= 16, ciphertext.count <= Self.maxRecordBytes + 16 else {
            throw PipaMobileError.invalidRecord
        }
        let header: [String: Any] = [
            "protocol_version": 2,
            "sequence": sequence,
            "session_id": sessionID,
        ]
        let nonce = receiveNoncePrefix + PipaMobileCodec.bigEndian(sequence)
        let aad = try PipaMobileCodec.canonicalJSON(header) + Data("pipa/json/v2".utf8)
        do {
            let box = ChaChaPoly.SealedBox(
                nonce: try ChaChaPoly.Nonce(data: nonce),
                ciphertext: Data(ciphertext.dropLast(16)),
                tag: Data(ciphertext.suffix(16))
            )
            let plaintext = try ChaChaPoly.open(box, using: receiveKey, authenticating: aad)
            guard plaintext.count <= Self.maxRecordBytes,
                  let object = try JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
                throw PipaMobileError.invalidRecord
            }
            receiveSequence += 1
            opened = true
            return object
        } catch let error as PipaMobileError {
            throw error
        } catch {
            throw PipaMobileError.invalidRecord
        }
    }
}

enum PipaMobileCodec {
    static func randomData(count: Int) -> Data {
        var generator = SystemRandomNumberGenerator()
        return Data((0..<count).map { _ in
            UInt8.random(in: UInt8.min...UInt8.max, using: &generator)
        })
    }

    static func canonicalJSON(_ object: [String: Any]) throws -> Data {
        guard JSONSerialization.isValidJSONObject(object) else {
            throw PipaMobileError.invalidMessage
        }
        do {
            return try JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
            )
        } catch {
            throw PipaMobileError.invalidMessage
        }
    }

    static func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func decodeBase64URL(_ value: String, expectedCount: Int? = nil) throws -> Data {
        guard !value.isEmpty,
              value.utf8.allSatisfy({
                  ($0 >= 0x41 && $0 <= 0x5A) ||
                      ($0 >= 0x61 && $0 <= 0x7A) ||
                      ($0 >= 0x30 && $0 <= 0x39) || $0 == 0x2D || $0 == 0x5F
              }),
              value.utf8.count % 4 != 1 else {
            throw PipaMobileError.invalidBase64
        }
        let standard = value.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = standard + String(repeating: "=", count: (4 - standard.utf8.count % 4) % 4)
        guard let data = Data(base64Encoded: padded),
              encodeBase64URL(data) == value,
              expectedCount == nil || data.count == expectedCount else {
            throw PipaMobileError.invalidBase64
        }
        return data
    }

    static func bigEndian(_ value: UInt64) -> Data {
        var number = value.bigEndian
        return withUnsafeBytes(of: &number) { Data($0) }
    }
}
