import CryptoKit
import XCTest

@testable import PipaMobileCore

final class PipaMobileProtocolTests: XCTestCase {
    func testClientHelloContainsOnlyTheExpectedPublicHandshakeFields() throws {
        let identity = try PipaMobileIdentity.generate(identityID: "ios-test")
        let context = try PipaMobileHandshake.makeClientHello(
            identity: identity,
            sessionID: "test-session"
        )

        XCTAssertEqual(Set(context.hello.keys), Set([
            "client_ephemeral_public_key",
            "client_id",
            "client_nonce",
            "protocol_version",
            "session_id",
            "signature",
        ]))
        XCTAssertEqual(context.hello["client_id"] as? String, "ios-test")
        XCTAssertEqual(context.hello["protocol_version"] as? Int, 2)
        XCTAssertEqual(
            try PipaMobileCodec.decodeBase64URL(
                context.hello["client_ephemeral_public_key"] as! String,
                expectedCount: 32
            ).count,
            32
        )
        XCTAssertEqual(
            try PipaMobileCodec.decodeBase64URL(
                context.hello["signature"] as! String,
                expectedCount: 64
            ).count,
            64
        )
    }

    func testCanonicalJSONIsCompactAndSortedLikeThePythonContract() throws {
        let data = try PipaMobileCodec.canonicalJSON([
            "z": "último",
            "a": 1,
        ])

        XCTAssertEqual(String(data: data, encoding: .utf8), "{\"a\":1,\"z\":\"último\"}")
    }

    func testMobileTextPolicyRejectsProtocolAndBidirectionalControls() {
        XCTAssertTrue(PipaMobileTextPolicy.containsProtocolControl("línea\nrota"))
        XCTAssertTrue(PipaMobileTextPolicy.containsDisplayControl("nombre\u{202E}oculto"))
        XCTAssertTrue(PipaMobileTextPolicy.containsDisplayControl("texto\u{0085}"))
        XCTAssertTrue(PipaMobileTextPolicy.containsDisplayControl("texto\u{E000}"))
        XCTAssertTrue(PipaMobileTextPolicy.isSafeDisplayText("texto visible", maxBytes: 64))
        XCTAssertFalse(PipaMobileTextPolicy.isSafeDisplayText("texto\u{200B}oculto", maxBytes: 64))
        XCTAssertTrue(PipaMobileTextPolicy.isSafeMessageText("línea 1\nlínea 2", maxBytes: 64))
        XCTAssertFalse(PipaMobileTextPolicy.isSafeMessageText("mensaje\u{0000}", maxBytes: 64))
    }

    func testDestinationPolicyUsesCanonicalPhoneAndDiscordIDs() {
        XCTAssertEqual(
            PipaMobileDestinationPolicy.normalizePhone("+34 600-123-456"),
            "34600123456"
        )
        XCTAssertNil(PipaMobileDestinationPolicy.normalizePhone("01234567"))
        XCTAssertEqual(
            PipaMobileDestinationPolicy.normalizeSnowflake("12345678901234567"),
            "12345678901234567"
        )
        XCTAssertNil(PipaMobileDestinationPolicy.normalizeSnowflake("012345678901234567"))
    }

    func testBase64URLRejectsPaddingAndInvalidCharacters() throws {
        XCTAssertThrowsError(try PipaMobileCodec.decodeBase64URL("a="))
        XCTAssertThrowsError(try PipaMobileCodec.decodeBase64URL("a+b"))
        // The final Base64URL character may not carry non-zero unused bits.
        XCTAssertThrowsError(try PipaMobileCodec.decodeBase64URL("AB"))
        XCTAssertEqual(
            try PipaMobileCodec.decodeBase64URL("AQID", expectedCount: 3),
            Data([1, 2, 3])
        )
    }

    func testMobileSettingsRoundTripDoesNotDependOnPrivateIdentityMaterial() throws {
        let settings = PipaMobileSettings(
            host: "192.168.1.20",
            port: "18765",
            serverID: "pipa-agent-v2",
            serverPublicKey: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA",
            identityID: "iphone-main"
        )
        let encoded = try JSONEncoder().encode(settings)
        let decoded = try JSONDecoder().decode(PipaMobileSettings.self, from: encoded)

        XCTAssertEqual(decoded, settings)
        XCTAssertFalse(String(data: encoded, encoding: .utf8)?.contains("privateKey") == true)
    }

    func testMobileSettingsRejectUnsafePersistedValuesBeforeTransport() throws {
        let valid = PipaMobileSettings(
            host: "192.168.1.20",
            port: "18765",
            serverID: "pipa-agent-v2",
            serverPublicKey: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA",
            identityID: "iphone-main"
        )
        XCTAssertNoThrow(try valid.validateForStorage())

        let partial = PipaMobileSettings(
            host: "",
            port: "18765",
            serverID: "pipa-agent-v2",
            serverPublicKey: "",
            identityID: "iphone-main"
        )
        XCTAssertNoThrow(try partial.validateForStorage())

        let invalidValues = [
            PipaMobileSettings(
                host: "8.8.8.8",
                port: "18765",
                serverID: valid.serverID,
                serverPublicKey: valid.serverPublicKey,
                identityID: valid.identityID
            ),
            PipaMobileSettings(
                host: valid.host,
                port: "18765\n443",
                serverID: valid.serverID,
                serverPublicKey: valid.serverPublicKey,
                identityID: valid.identityID
            ),
            PipaMobileSettings(
                host: valid.host,
                port: valid.port,
                serverID: "pipa-agent\u{202E}v2",
                serverPublicKey: valid.serverPublicKey,
                identityID: valid.identityID
            ),
            PipaMobileSettings(
                host: valid.host,
                port: valid.port,
                serverID: valid.serverID,
                serverPublicKey: "not-a-key",
                identityID: valid.identityID
            ),
        ]

        for settings in invalidValues {
            XCTAssertThrowsError(try settings.validateForStorage())
        }
    }

    func testFingerprintIsPublicAndStable() throws {
        let identity = try PipaMobileIdentity.generate(identityID: "ios-test")
        let second = try PipaMobileIdentity(
            identityID: "ios-test",
            privateKey: identity.privateKey
        )

        XCTAssertEqual(identity.fingerprint, second.fingerprint)
        XCTAssertEqual(identity.fingerprint.split(separator: ":").count, 32)
    }

    func testPinnedServerFingerprintUsesOnlyThePublicKey() {
        let publicKey = Data(repeating: 0x42, count: 32)

        let fingerprint = PipaMobileIdentity.publicKeyDigest(forPublicKeyData: publicKey)

        XCTAssertEqual(fingerprint?.split(separator: ":").count, 32)
        XCTAssertNil(PipaMobileIdentity.publicKeyDigest(forPublicKeyData: Data(repeating: 0x42, count: 31)))
    }

    @available(iOS 16.0, *)
    func testMobileEndpointRejectsPublicAndWildcardHosts() {
        XCTAssertTrue(PipaMobileTCPClient.isAllowedHost("192.168.1.20"))
        XCTAssertTrue(PipaMobileTCPClient.isAllowedHost("127.0.0.1"))
        XCTAssertTrue(PipaMobileTCPClient.isAllowedHost("169.254.1.10"))
        XCTAssertTrue(PipaMobileTCPClient.isAllowedHost("::1"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("192.168.001.020"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("010.0.0.1"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("8.8.8.8"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("0.0.0.0"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("pipa.example"))
        XCTAssertFalse(PipaMobileTCPClient.isAllowedHost("١٩٢.١٦٨.١.٢٠"))
    }

    func testRecordLayerEncryptsAuthenticatesAndRejectsReplay() throws {
        let clientPrivate = Curve25519.KeyAgreement.PrivateKey()
        let serverPrivate = Curve25519.KeyAgreement.PrivateKey()
        let clientShared = try clientPrivate.sharedSecretFromKeyAgreement(with: serverPrivate.publicKey)
        let serverShared = try serverPrivate.sharedSecretFromKeyAgreement(with: clientPrivate.publicKey)
        let transcriptHash = Data(repeating: 0x42, count: 32)
        let client = try PipaSecureRecordLayer(
            sessionID: "swift-record-test",
            sharedSecret: clientShared,
            transcriptHash: transcriptHash,
            role: .client
        )
        let server = try PipaSecureRecordLayer(
            sessionID: "swift-record-test",
            sharedSecret: serverShared,
            transcriptHash: transcriptHash,
            role: .server
        )
        let payload: [String: Any] = [
            "protocol_version": 1,
            "type": "ping",
            "request_id": "swift-test",
        ]

        let frame = try client.seal(payload: payload)
        XCTAssertEqual(try server.open(frame: frame)["type"] as? String, "ping")
        XCTAssertThrowsError(try server.open(frame: frame))
        XCTAssertThrowsError(try server.open(frame: frame)) { error in
            guard case PipaMobileError.sessionClosed = error else {
                return XCTFail("Expected the record layer to fail closed")
            }
        }
    }

    func testRecordLayerMatchesTheSharedPythonVector() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("../Fixtures/mobile_record_v2.json")
            .standardizedFileURL
        let fixtureData = try Data(contentsOf: fixtureURL)
        let fixture = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: fixtureData) as? [String: Any]
        )
        let sharedSecretData = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["shared_secret"] as? String),
            expectedCount: 32
        )
        let transcriptHash = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["transcript_hash"] as? String),
            expectedCount: 32
        )
        let payload = try XCTUnwrap(fixture["payload"] as? [String: Any])
        let client = try PipaSecureRecordLayer(
            sessionID: try XCTUnwrap(fixture["session_id"] as? String),
            sharedSecretData: sharedSecretData,
            transcriptHash: transcriptHash,
            role: .client
        )
        let server = try PipaSecureRecordLayer(
            sessionID: try XCTUnwrap(fixture["session_id"] as? String),
            sharedSecretData: sharedSecretData,
            transcriptHash: transcriptHash,
            role: .server
        )

        let frame = try client.seal(payload: payload)
        XCTAssertEqual(
            frame["ciphertext"] as? String,
            fixture["ciphertext_and_tag"] as? String
        )
        XCTAssertEqual(try server.open(frame: frame)["type"] as? String, "ping")
    }

    func testHandshakeMatchesTheSharedPythonVector() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("../Fixtures/mobile_handshake_v2.json")
            .standardizedFileURL
        let fixtureData = try Data(contentsOf: fixtureURL)
        let fixture = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: fixtureData) as? [String: Any]
        )
        let clientSeed = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["client_identity_seed"] as? String),
            expectedCount: 32
        )
        let serverPublicKey = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["server_public_key"] as? String),
            expectedCount: 32
        )
        let clientEphemeral = try Curve25519.KeyAgreement.PrivateKey(
            rawRepresentation: try PipaMobileCodec.decodeBase64URL(
                try XCTUnwrap(fixture["client_ephemeral_private_key"] as? String),
                expectedCount: 32
            )
        )
        let clientNonce = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["client_nonce"] as? String),
            expectedCount: 32
        )
        let identity = try PipaMobileIdentity(
            identityID: try XCTUnwrap(fixture["client_id"] as? String),
            privateKey: try Curve25519.Signing.PrivateKey(rawRepresentation: clientSeed)
        )
        let context = try PipaMobileHandshake.makeClientHello(
            identity: identity,
            sessionID: try XCTUnwrap(fixture["session_id"] as? String),
            ephemeralPrivateKey: clientEphemeral,
            clientNonce: clientNonce
        )
        let expectedClientHello = try XCTUnwrap(fixture["client_hello"] as? [String: Any])
        XCTAssertEqual(
            try PipaMobileCodec.canonicalJSON(context.hello),
            try PipaMobileCodec.canonicalJSON(expectedClientHello)
        )

        let serverHello = try XCTUnwrap(fixture["server_hello"] as? [String: Any])
        let layer = try PipaMobileHandshake.complete(
            context: context,
            serverHello: serverHello,
            serverPublicKeyData: serverPublicKey,
            expectedServerID: try XCTUnwrap(fixture["server_id"] as? String)
        )
        let payload = try XCTUnwrap(fixture["payload"] as? [String: Any])
        let frame = try layer.seal(payload: payload)
        XCTAssertEqual(
            frame["ciphertext"] as? String,
            try XCTUnwrap((fixture["client_frame"] as? [String: Any])?["ciphertext"] as? String)
        )
    }

    func testSecureAudioFrameMatchesTheSharedPythonVector() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("../Fixtures/secure_audio_v2.json")
            .standardizedFileURL
        let fixtureData = try Data(contentsOf: fixtureURL)
        let fixture = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: fixtureData) as? [String: Any]
        )
        let sharedSecret = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["shared_secret"] as? String),
            expectedCount: 32
        )
        let transcriptHash = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["transcript_hash"] as? String),
            expectedCount: 32
        )
        let samples = try PipaMobileCodec.decodeBase64URL(
            try XCTUnwrap(fixture["samples"] as? String),
            expectedCount: 32
        )
        let expectedFrame = try XCTUnwrap(fixture["frame"] as? [String: Any])
        let sessionID = try XCTUnwrap(fixture["session_id"] as? String)
        let client = try PipaSecureRecordLayer(
            sessionID: sessionID,
            sharedSecretData: sharedSecret,
            transcriptHash: transcriptHash,
            role: .client
        )
        let server = try PipaSecureRecordLayer(
            sessionID: sessionID,
            sharedSecretData: sharedSecret,
            transcriptHash: transcriptHash,
            role: .server
        )

        let sender = try PipaSecureAudioSender(
            layer: client,
            streamID: try XCTUnwrap(fixture["stream_id"] as? String)
        )
        let frame = try sender.sealChunk(samples: samples, final: true)
        XCTAssertEqual(frame["ciphertext"] as? String, expectedFrame["ciphertext"] as? String)
        XCTAssertEqual(frame["audio_protocol_version"] as? Int, 2)
        XCTAssertFalse(frame.keys.contains("samples"))

        let receiver = PipaSecureAudioReceiver(layer: server)
        XCTAssertEqual(try receiver.open(frame: frame), samples)
        XCTAssertTrue(receiver.isComplete)
        XCTAssertEqual(receiver.streamByteCount, 32)
    }

    func testSecureAudioRejectsReorderedAndTamperedFrames() throws {
        let sharedSecret = Data((1...32).map(UInt8.init))
        let transcriptHash = Data((32...63).map(UInt8.init))
        let client = try PipaSecureRecordLayer(
            sessionID: "audio-test",
            sharedSecretData: sharedSecret,
            transcriptHash: transcriptHash,
            role: .client
        )
        let server = try PipaSecureRecordLayer(
            sessionID: "audio-test",
            sharedSecretData: sharedSecret,
            transcriptHash: transcriptHash,
            role: .server
        )
        let sender = try PipaSecureAudioSender(layer: client, streamID: "ordered")
        let first = try sender.sealChunk(samples: Data([0, 1, 2, 3]), final: false)
        let second = try sender.sealChunk(samples: Data([4, 5, 6, 7]), final: true)
        let receiver = PipaSecureAudioReceiver(layer: server)

        XCTAssertThrowsError(try receiver.open(frame: second))
        XCTAssertThrowsError(try receiver.open(frame: first))
    }

    @available(iOS 16.0, macOS 13.0, *)
    func testTCPClientRejectsInvalidTextAndOversizedArgumentsBeforeTransport() async throws {
        let identity = try PipaMobileIdentity.generate(identityID: "ios-client")
        let client = try PipaMobileTCPClient(
            identity: identity,
            serverPublicKeyData: Data(repeating: 0x42, count: 32),
            serverID: "pipa-agent-v2"
        )

        do {
            _ = try await client.sendText("comando\nno permitido")
            XCTFail("control characters must be rejected locally")
        } catch PipaMobileError.invalidMessage {
            // Expected.
        }

        do {
            _ = try await client.sendText("comando\u{202E}oculto")
            XCTFail("bidirectional controls must be rejected locally")
        } catch PipaMobileError.invalidMessage {
            // Expected.
        }

        do {
            _ = try await client.callTool(
                name: "open_url",
                arguments: ["url": String(repeating: "x", count: 5000)]
            )
            XCTFail("oversized tool arguments must be rejected locally")
        } catch PipaMobileError.payloadTooLarge {
            // Expected.
        }
    }
}
