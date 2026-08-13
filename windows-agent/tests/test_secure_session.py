import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey  # noqa: E402
from secure_session import (  # noqa: E402
    ClientHello,
    HandshakeError,
    RecordError,
    ReplayError,
    SecureIdentity,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
    create_server_hello,
    secure_session_from_shared_secret,
)
from secure_session_server import MAX_USED_SESSION_IDS, SecureSessionServer  # noqa: E402


class SecureSessionTests(unittest.TestCase):
    def setUp(self):
        self.client_identity = SecureIdentity("waveshare-test", Ed25519PrivateKey.generate())
        self.server_identity = SecureIdentity("pipa-agent-test", Ed25519PrivateKey.generate())
        self.client_hello, self.client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="session-test",
            ephemeral_private_key=X25519PrivateKey.from_private_bytes(bytes(range(1, 33))),
            nonce=bytes(range(32)),
        )
        self.server_hello, self.server_session = create_server_hello(
            self.server_identity,
            self.client_hello,
            self.client_identity.public_key,
            ephemeral_private_key=X25519PrivateKey.from_private_bytes(bytes(range(33, 65))),
            nonce=bytes(range(32, 64)),
        )
        self.client_session = complete_client_handshake(
            self.client_identity,
            self.client_hello,
            self.client_ephemeral,
            self.server_hello,
            self.server_identity.public_key,
        )

    def test_both_roles_derive_compatible_directional_keys(self):
        frame = self.client_session.seal(b"mensaje privado")
        self.assertEqual(self.server_session.open(frame), b"mensaje privado")

        response = self.server_session.seal(b"respuesta")
        self.assertEqual(self.client_session.open(response), b"respuesta")

    def test_transport_independent_server_adapter_completes_handshake(self):
        server = SecureSessionServer(
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )
        server_payload, server_session = server.accept_client_hello(self.client_hello.as_dict())
        client_session = complete_client_handshake(
            self.client_identity,
            self.client_hello,
            self.client_ephemeral,
            type(self.server_hello)(**server_payload),
            self.server_identity.public_key,
            expected_server_id=self.server_identity.identity_id,
        )
        frame = client_session.seal(b"server adapter")
        self.assertEqual(server_session.open(frame), b"server adapter")

    def test_transport_independent_server_rejects_unknown_or_extra_fields(self):
        server = SecureSessionServer(self.server_identity, {})
        with self.assertRaises(HandshakeError):
            server.accept_client_hello(self.client_hello.as_dict() | {"extra": True})
        with self.assertRaises(HandshakeError):
            server.accept_client_hello(self.client_hello.as_dict() | {"client_id": "unknown"})

    def test_transport_independent_server_rejects_client_hello_replay(self):
        server = SecureSessionServer(
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )
        server.accept_client_hello(self.client_hello.as_dict())
        with self.assertRaises(HandshakeError):
            server.accept_client_hello(self.client_hello.as_dict())

    def test_server_refresh_rejects_a_revoked_device(self):
        server = SecureSessionServer(
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )
        server.refresh_trusted_devices({})

        with self.assertRaises(HandshakeError):
            server.accept_client_hello(self.client_hello.as_dict())

    def test_transport_independent_server_bounds_replay_cache(self):
        server = SecureSessionServer(
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )
        self.assertGreater(MAX_USED_SESSION_IDS, 1)
        with patch("secure_session_server.MAX_USED_SESSION_IDS", 1):
            server.accept_client_hello(self.client_hello.as_dict())
            second_hello, _ = create_client_hello(self.client_identity, session_id="second-session")
            server.accept_client_hello(second_hello.as_dict())

        self.assertEqual(len(server._used_session_ids), 1)
        self.assertIn("second-session", server._used_session_ids)

    def test_handshake_rejects_wrong_server_identity(self):
        with self.assertRaises(HandshakeError):
            complete_client_handshake(
                self.client_identity,
                self.client_hello,
                self.client_ephemeral,
                self.server_hello,
                Ed25519PrivateKey.generate().public_key(),
            )

    def test_handshake_rejects_tampered_ephemeral_key(self):
        tampered = ClientHello(
            **{
                **self.client_hello.as_dict(),
                "client_ephemeral_public_key": self.server_hello.server_ephemeral_public_key,
            }
        )
        with self.assertRaises(HandshakeError):
            create_server_hello(self.server_identity, tampered, self.client_identity.public_key)

    def test_handshake_rejects_noncanonical_base64url(self):
        tampered = {
            **self.client_hello.as_dict(),
            "client_nonce": "A" * 42 + "B",
        }

        with self.assertRaises(HandshakeError):
            ClientHello(**tampered)

    def test_handshake_rejects_server_rewriting_client_transcript(self):
        transcript = {
            **self.server_hello.transcript_dict(),
            "client_nonce": base64.urlsafe_b64encode(b"x" * 32).decode("ascii").rstrip("="),
        }
        signed = json.dumps(
            {"role": "server", **transcript},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = (
            base64.urlsafe_b64encode(self.server_identity.private_key.sign(signed))
            .decode("ascii")
            .rstrip("=")
        )
        tampered = ServerHello(**transcript, signature=signature)
        with self.assertRaises(HandshakeError):
            complete_client_handshake(
                self.client_identity,
                self.client_hello,
                self.client_ephemeral,
                tampered,
                self.server_identity.public_key,
            )

        with self.assertRaises(HandshakeError):
            complete_client_handshake(
                self.client_identity,
                self.client_hello,
                self.client_ephemeral,
                self.server_hello,
                self.server_identity.public_key,
                expected_server_id="another-agent",
            )

    def test_records_bind_session_header_and_aad(self):
        frame = self.client_session.seal(b"payload", additional_data=b"route:usb")
        with self.assertRaises(RecordError):
            self.server_session.open(frame, additional_data=b"route:mobile")

    def test_replay_and_out_of_order_records_are_rejected(self):
        frame = self.client_session.seal(b"once")
        self.assertEqual(self.server_session.open(frame), b"once")
        with self.assertRaises(ReplayError):
            self.server_session.open(frame)

        later = self.client_session.seal(b"later")
        earlier = self.client_session.seal(b"earlier")
        with self.assertRaises(ReplayError):
            self.server_session.open(earlier)
        self.assertEqual(self.server_session.open(later), b"later")
        self.assertEqual(self.server_session.open(earlier), b"earlier")

    def test_close_is_fail_closed(self):
        self.client_session.close()
        with self.assertRaises(RecordError):
            self.client_session.seal(b"no")

    def test_firmware_cross_language_vector(self):
        vector_path = (
            Path(__file__).resolve().parents[2] / "firmware" / "test_vectors" / "secure_session_v2.json"
        )
        vector = json.loads(vector_path.read_text(encoding="utf-8"))

        def decode(value):
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

        shared_secret = decode(vector["shared_secret"])
        transcript_hash = decode(vector["transcript_hash"])
        client = secure_session_from_shared_secret(
            vector["session_id"],
            shared_secret,
            transcript_hash,
            role="client",
        )
        server = secure_session_from_shared_secret(
            vector["session_id"],
            shared_secret,
            transcript_hash,
            role="server",
        )

        frame = client.seal(
            vector["plaintext"].encode("utf-8"),
            additional_data=vector["additional_data"].encode("utf-8"),
        )
        self.assertEqual(
            frame["ciphertext"],
            vector["ciphertext_and_tag"],
        )
        self.assertEqual(
            server.open(frame, additional_data=vector["additional_data"].encode("utf-8")),
            vector["plaintext"].encode("utf-8"),
        )

    def test_mobile_swift_cross_language_vector(self):
        vector_path = (
            Path(__file__).resolve().parents[2]
            / "mobile-ios"
            / "Tests"
            / "Fixtures"
            / "mobile_record_v2.json"
        )
        vector = json.loads(vector_path.read_text(encoding="utf-8"))

        def decode(value):
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

        client = secure_session_from_shared_secret(
            vector["session_id"],
            decode(vector["shared_secret"]),
            decode(vector["transcript_hash"]),
            role="client",
        )
        server = secure_session_from_shared_secret(
            vector["session_id"],
            decode(vector["shared_secret"]),
            decode(vector["transcript_hash"]),
            role="server",
        )
        frame = client.seal(
            vector["plaintext"].encode("utf-8"),
            additional_data=vector["additional_data"].encode("utf-8"),
        )
        self.assertEqual(frame["ciphertext"], vector["ciphertext_and_tag"])
        self.assertEqual(
            server.open(frame, additional_data=vector["additional_data"].encode("utf-8")),
            vector["plaintext"].encode("utf-8"),
        )

    def test_mobile_handshake_cross_language_vector(self):
        vector_path = (
            Path(__file__).resolve().parents[2]
            / "mobile-ios"
            / "Tests"
            / "Fixtures"
            / "mobile_handshake_v2.json"
        )
        vector = json.loads(vector_path.read_text(encoding="utf-8"))

        def decode(value):
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

        client_identity = SecureIdentity(
            vector["client_id"],
            Ed25519PrivateKey.from_private_bytes(decode(vector["client_identity_seed"])),
        )
        server_identity = SecureIdentity(
            vector["server_id"],
            Ed25519PrivateKey.from_private_bytes(decode(vector["server_identity_seed"])),
        )
        self.assertEqual(client_identity.public_key_b64, vector["client_public_key"])
        self.assertEqual(server_identity.public_key_b64, vector["server_public_key"])
        client_hello, client_ephemeral = create_client_hello(
            client_identity,
            session_id=vector["session_id"],
            ephemeral_private_key=X25519PrivateKey.from_private_bytes(
                decode(vector["client_ephemeral_private_key"])
            ),
            nonce=decode(vector["client_nonce"]),
        )
        server_hello, server_session = create_server_hello(
            server_identity,
            client_hello,
            client_identity.public_key,
            ephemeral_private_key=X25519PrivateKey.from_private_bytes(
                decode(vector["server_ephemeral_private_key"])
            ),
            nonce=decode(vector["server_nonce"]),
        )
        client_session = complete_client_handshake(
            client_identity,
            client_hello,
            client_ephemeral,
            server_hello,
            server_identity.public_key,
            expected_server_id=vector["server_id"],
        )
        self.assertEqual(client_hello.as_dict(), vector["client_hello"])
        self.assertEqual(server_hello.as_dict(), vector["server_hello"])

        frame = client_session.seal(
            vector["plaintext"].encode("utf-8"),
            additional_data=vector["additional_data"].encode("utf-8"),
        )
        self.assertEqual(frame, vector["client_frame"])
        self.assertEqual(
            server_session.open(frame, additional_data=vector["additional_data"].encode("utf-8")),
            vector["plaintext"].encode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
