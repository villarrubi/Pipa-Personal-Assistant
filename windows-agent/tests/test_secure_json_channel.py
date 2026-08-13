import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_json_channel import SECURE_JSON_AAD, SecureJsonChannel, SecureJsonError  # noqa: E402
from secure_session import (  # noqa: E402
    RecordError,
    SecureIdentity,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
)
from secure_session_server import SecureSessionServer  # noqa: E402


class SecureJsonChannelTests(unittest.TestCase):
    def setUp(self):
        client_identity = SecureIdentity("waveshare-test", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-agent-test", Ed25519PrivateKey.generate())
        client_hello, client_ephemeral = create_client_hello(client_identity, session_id="json-session")
        server = SecureSessionServer(
            server_identity, {client_identity.identity_id: client_identity.public_key}
        )
        server_payload, server_session = server.accept_client_hello(client_hello.as_dict())
        client_session = complete_client_handshake(
            client_identity,
            client_hello,
            client_ephemeral,
            ServerHello(**server_payload),
            server_identity.public_key,
            expected_server_id=server_identity.identity_id,
        )
        self.client = SecureJsonChannel(client_session)
        self.server = SecureJsonChannel(server_session)

    def test_payload_is_encrypted_and_round_trips_as_an_object(self):
        payload = {"protocol_version": 1, "type": "ping", "request_id": "private-request"}
        frame = self.client.seal_message(payload)
        self.assertNotIn("private-request", str(frame))
        self.assertEqual(self.server.open_message(frame), payload)

    def test_outer_frame_and_json_payload_are_strict(self):
        frame = self.client.seal_message({"type": "ping"})
        with self.assertRaises(SecureJsonError):
            self.server.open_message(frame | {"extra": True})
        self.assertEqual(self.server.open_message(frame), {"type": "ping"})

        duplicate_frame = self.client.session.seal(b'{"a":1,"a":2}', additional_data=SECURE_JSON_AAD)
        with self.assertRaises(SecureJsonError):
            self.server.open_message(duplicate_frame)

    def test_non_object_nan_and_oversized_payloads_are_rejected(self):
        with self.assertRaises(SecureJsonError):
            self.client.seal_message(["not", "an", "object"])
        with self.assertRaises(SecureJsonError):
            self.client.seal_message({"value": float("nan")})
        with self.assertRaises(SecureJsonError):
            self.client.seal_message({"value": "x" * (64 * 1024 + 1)})

    def test_wrong_aad_is_not_accepted(self):
        frame = self.client.session.seal(b'{"type":"ping"}')
        with self.assertRaises(RecordError):
            self.server.session.open(frame, additional_data=b"wrong-route")


if __name__ == "__main__":
    unittest.main()
