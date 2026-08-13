import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_core_connection import SecureCoreConnection  # noqa: E402
from secure_json_channel import SecureJsonChannel  # noqa: E402
from secure_session import (  # noqa: E402
    SecureIdentity,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
)

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402


class SecureCoreConnectionTests(unittest.TestCase):
    def test_encrypted_ping_round_trips_through_the_core(self):
        client_identity = SecureIdentity("waveshare-v2", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        core = PipaCore(verifier=object(), router=ToolRouter(ToolCatalog([])))
        connection = SecureCoreConnection(
            core,
            server_identity,
            {client_identity.identity_id: client_identity.public_key},
        )

        client_hello, client_ephemeral = create_client_hello(client_identity, session_id="core-session")
        server_payload = connection.accept_client_hello(client_hello.as_dict())
        client_session = complete_client_handshake(
            client_identity,
            client_hello,
            client_ephemeral,
            ServerHello(**server_payload),
            server_identity.public_key,
            expected_server_id=server_identity.identity_id,
        )
        client_channel = SecureJsonChannel(client_session)
        frames = connection.process_frame(
            client_channel.seal_message({"protocol_version": 1, "type": "ping", "request_id": "round-trip"})
        )
        responses = [client_channel.open_message(frame) for frame in frames]

        self.assertEqual(responses, [{"protocol_version": 1, "type": "pong", "request_id": "round-trip"}])
        self.assertEqual(core.sessions.count(), 1)
        connection.close()
        self.assertEqual(core.sessions.count(), 0)

    def test_invalid_core_payload_is_reported_inside_the_encrypted_channel(self):
        client_identity = SecureIdentity("waveshare-v2", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        core = PipaCore(verifier=object(), router=ToolRouter(ToolCatalog([])))
        connection = SecureCoreConnection(
            core,
            server_identity,
            {client_identity.identity_id: client_identity.public_key},
        )
        client_hello, client_ephemeral = create_client_hello(client_identity, session_id="core-errors")
        server_payload = connection.accept_client_hello(client_hello.as_dict())
        client_channel = SecureJsonChannel(
            complete_client_handshake(
                client_identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                server_identity.public_key,
            )
        )

        frames = connection.process_frame(
            client_channel.seal_message({"protocol_version": 1, "type": "unknown"})
        )
        self.assertEqual(client_channel.open_message(frames[0])["code"], "protocol_error")
        connection.close()

    def test_secure_session_announces_capabilities_before_external_confirmation(self):
        client_identity = SecureIdentity("waveshare-v2", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        executed = []
        catalog = ToolCatalog(
            [
                ToolDefinition(
                    "unsafe",
                    lambda arguments: executed.append(arguments) or {"success": True},
                    safety="unsafe",
                    confirm_summary=lambda _arguments: "Acción externa",
                )
            ]
        )
        core = PipaCore(verifier=object(), router=ToolRouter(catalog))
        connection = SecureCoreConnection(
            core,
            server_identity,
            {client_identity.identity_id: client_identity.public_key},
        )
        client_hello, client_ephemeral = create_client_hello(client_identity, session_id="core-caps")
        server_payload = connection.accept_client_hello(client_hello.as_dict())
        client_channel = SecureJsonChannel(
            complete_client_handshake(
                client_identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                server_identity.public_key,
            )
        )

        before = connection.process_frame(
            client_channel.seal_message(
                {"protocol_version": 1, "type": "tool_call", "name": "unsafe", "arguments": {}}
            )
        )
        before_responses = [client_channel.open_message(frame) for frame in before]
        self.assertEqual(before_responses[0]["code"], "device_hello_required")

        hello_ack = connection.process_frame(
            client_channel.seal_message(
                {
                    "protocol_version": 1,
                    "type": "device_hello",
                    "firmware_version": "0.2.0",
                    "capabilities": ["display", "touch"],
                }
            )
        )
        self.assertEqual(client_channel.open_message(hello_ack[0])["type"], "device_hello_ack")

        after = connection.process_frame(
            client_channel.seal_message(
                {"protocol_version": 1, "type": "tool_call", "name": "unsafe", "arguments": {}}
            )
        )
        self.assertEqual(client_channel.open_message(after[0])["type"], "confirm_request")
        self.assertEqual(executed, [])
        connection.close()


if __name__ == "__main__":
    unittest.main()
