import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_core_connection import SecureCoreConnection  # noqa: E402
from secure_mobile_client import SecureMobileClient  # noqa: E402
from secure_session import SecureIdentity  # noqa: E402
from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.integration_catalog import get_command_catalog  # noqa: E402
from tools.timers import TimerManager  # noqa: E402

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402


class SecureMobileClientTests(unittest.TestCase):
    def _build(self):
        mobile_identity = SecureIdentity("mobile-reference", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        executed = []
        catalog = ToolCatalog(
            [
                ToolDefinition(
                    "external_test",
                    lambda arguments: executed.append(arguments) or {"success": True},
                    safety="unsafe",
                    confirm_summary=lambda _arguments: "Acción externa de prueba",
                )
            ]
        )
        core = PipaCore(
            verifier=object(),
            router=ToolRouter(catalog),
            command_catalog=lambda: [
                {
                    "id": "external_test",
                    "tool_name": "external_test",
                    "phrase": "acción externa de prueba",
                    "description": "Acción externa de prueba.",
                    "safety": "unsafe",
                    "requires_confirmation": True,
                }
            ],
            capability_catalog=lambda: {
                "apple_music": {
                    "available": True,
                    "playback": False,
                    "requires_manual_selection": True,
                }
            },
        )
        connection = SecureCoreConnection(
            core,
            server_identity,
            {mobile_identity.identity_id: mobile_identity.public_key},
        )
        client = SecureMobileClient(
            mobile_identity,
            server_identity.public_key,
            server_id=server_identity.identity_id,
        )
        return client, connection, executed

    def test_mobile_flow_is_encrypted_and_confirmation_gated(self):
        client, connection, executed = self._build()

        self.assertEqual(client.connect(connection)[0]["type"], "device_hello_ack")
        catalog = client.request_catalog()
        self.assertEqual(catalog[0]["tool_name"], "external_test")
        self.assertNotIn("result", catalog[0])
        details = client.request_catalog_details()
        self.assertEqual(details["capabilities"]["apple_music"]["playback"], False)
        pending = client.send_text("acción externa de prueba")

        self.assertEqual(pending[0]["type"], "error")
        self.assertEqual(pending[0]["code"], "unsupported_text_intent")
        self.assertEqual(executed, [])

        pending = client.call_tool("external_test", {}, call_id="mobile-call")
        self.assertEqual(pending[0]["type"], "confirm_request")
        self.assertEqual(pending[0]["call_id"], "mobile-call")
        self.assertEqual(executed, [])

        completed = client.confirm(pending[0]["confirmation_id"], True)
        self.assertEqual(completed[0]["type"], "tool_result")
        self.assertTrue(completed[0]["success"])
        self.assertEqual(completed[0]["call_id"], "mobile-call")
        self.assertNotIn("result", completed[0])
        self.assertEqual(executed, [{}])
        client.close()

    def test_real_catalog_preserves_direct_no_argument_actions(self):
        mobile_identity = SecureIdentity("mobile-catalog", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("pipa-catalog", Ed25519PrivateKey.generate())
        core = PipaCore(
            verifier=object(),
            router=ToolRouter(build_agent_catalog(TimerManager())),
            command_catalog=get_command_catalog,
        )
        connection = SecureCoreConnection(
            core,
            server_identity,
            {mobile_identity.identity_id: mobile_identity.public_key},
        )
        client = SecureMobileClient(
            mobile_identity,
            server_identity.public_key,
            server_id=server_identity.identity_id,
        )

        try:
            client.connect(connection)
            details = client.request_catalog_details()
            command = next(item for item in details["commands"] if item["id"] == "discord_open_app")
            self.assertEqual(command["parameters"], [])
            league_command = next(item for item in details["commands"] if item["id"] == "league_search")
            self.assertEqual(
                league_command["parameters"][0]["name"],
                "queue",
            )
        finally:
            client.close()

    def test_mobile_client_rejects_a_wrong_pinned_server(self):
        client, connection, _executed = self._build()
        wrong_server = Ed25519PrivateKey.generate().public_key()
        client.server_public_key = wrong_server

        with self.assertRaises(ValueError):
            client.connect(connection)

        self.assertFalse(client.connected)
        self.assertEqual(connection.core.sessions.count(), 0)

    @patch("secure_mobile_client.create_client_hello")
    def test_client_does_not_open_a_transport_or_persist_identity(self, create_hello):
        client, _connection, _executed = self._build()
        create_hello.side_effect = RuntimeError("test")

        with self.assertRaises(TypeError):
            client.connect("not-a-transport")

        create_hello.assert_not_called()


if __name__ == "__main__":
    unittest.main()
