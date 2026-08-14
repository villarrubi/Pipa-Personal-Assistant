import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_mobile_tcp_client import SecureMobileTcpClient  # noqa: E402
from secure_session import SecureIdentity, create_client_hello  # noqa: E402
from secure_tcp_gateway import (  # noqa: E402
    SecureTcpGateway,
    start_configured_mobile_gateway,
    validate_mobile_bind_host,
)
from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.timers import TimerManager  # noqa: E402
from trusted_unlock_devices import DeviceStoreError  # noqa: E402

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.request_binding import compute_request_digest  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402


class SecureTcpGatewayTests(unittest.TestCase):
    def _build(self):
        mobile_identity = SecureIdentity("mobile-tcp-test", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("server-tcp-test", Ed25519PrivateKey.generate())
        executed: list[dict[str, object]] = []
        catalog = ToolCatalog(
            [
                ToolDefinition(
                    "external_test",
                    lambda arguments: executed.append(arguments) or {"success": True},
                    safety="unsafe",
                    confirm_summary=lambda _arguments: "Acción TCP de prueba",
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
                    "phrase": "acción TCP de prueba",
                    "description": "Acción TCP de prueba.",
                    "safety": "unsafe",
                    "requires_confirmation": True,
                }
            ],
            capability_catalog=lambda: {
                "discord": {
                    "available": True,
                    "start_call": False,
                    "requires_manual_call": True,
                }
            },
        )
        gateway = SecureTcpGateway(
            core,
            "127.0.0.1",
            0,
            server_identity,
            {mobile_identity.identity_id: mobile_identity.public_key},
        )
        client = SecureMobileTcpClient(
            mobile_identity,
            server_identity.public_key,
            server_id=server_identity.identity_id,
        )
        return core, gateway, client, server_identity, executed

    def test_real_loopback_round_trip_is_encrypted_and_confirmation_gated(self):
        core, gateway, client, _server_identity, executed = self._build()

        async def exercise():
            gateway.start()
            try:
                self.assertEqual(
                    (await client.connect(gateway.bind_host, gateway.port))[0]["type"], "device_hello_ack"
                )
                catalog = await client.request_catalog()
                self.assertEqual(catalog[0]["tool_name"], "external_test")
                self.assertNotIn("result", catalog[0])
                details = await client.request_catalog_details()
                self.assertEqual(details["capabilities"]["discord"]["start_call"], False)
                pending = await client.call_tool("external_test", {}, call_id="tcp-call")
                self.assertEqual(pending[0]["type"], "confirm_request")
                self.assertEqual(pending[0]["call_id"], "tcp-call")
                self.assertEqual(pending[0]["request_digest"], compute_request_digest("external_test", {}))
                self.assertEqual(executed, [])
                completed = await client.confirm(pending[0]["confirmation_id"], True)
                self.assertEqual(completed[0]["type"], "tool_result")
                self.assertNotIn("result", completed[0])
                self.assertEqual(executed, [{}])
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exercise())
        self.assertEqual(core.sessions.count(), 0)

    @patch("webbrowser.open", return_value=True)
    @patch("tools.agent_catalog.resolve_discord_contact")
    @patch("tools.agent_catalog.with_client_or_launch")
    def test_real_loopback_runs_the_five_integrations_only_after_confirmation(
        self,
        with_client_or_launch,
        resolve_discord_contact,
        open_browser,
    ):
        """Exercise the mobile path with the real catalog and adapters."""

        class FakeLeagueClient:
            def start_search(self, queue):
                return {"started": True, "queue": queue}

        with_client_or_launch.side_effect = lambda callback, _launcher: callback(FakeLeagueClient())
        resolve_discord_contact.return_value = ("amigo", "12345678901234567", None)
        mobile_identity = SecureIdentity("mobile-integrations", Ed25519PrivateKey.generate())
        server_identity = SecureIdentity("server-integrations", Ed25519PrivateKey.generate())
        core = PipaCore(
            verifier=object(),
            router=ToolRouter(build_agent_catalog(TimerManager())),
        )
        gateway = SecureTcpGateway(
            core,
            "127.0.0.1",
            0,
            server_identity,
            {mobile_identity.identity_id: mobile_identity.public_key},
        )
        client = SecureMobileTcpClient(
            mobile_identity,
            server_identity.public_key,
            server_id=server_identity.identity_id,
        )
        actions = (
            ("web_search", {"query": "documentación de Pipa"}),
            ("music_search", {"term": "Daft Punk"}),
            ("whatsapp_compose", {"phone": "+34600123456", "message": "mensaje de prueba"}),
            ("discord_call", {"contact": "amigo"}),
            ("league_search", {"queue": "normal_draft"}),
        )

        async def exercise():
            gateway.start()
            try:
                await client.connect(gateway.bind_host, gateway.port)
                for index, (name, arguments) in enumerate(actions):
                    browser_calls = open_browser.call_count
                    alias_calls = resolve_discord_contact.call_count
                    league_calls = with_client_or_launch.call_count
                    pending = await client.call_tool(name, arguments, call_id=f"mobile-{index}")
                    self.assertEqual(pending[0]["type"], "confirm_request")
                    self.assertEqual(pending[0]["call_id"], f"mobile-{index}")
                    self.assertNotIn("600123456", str(pending))
                    self.assertNotIn("mensaje de prueba", str(pending))
                    self.assertEqual(open_browser.call_count, browser_calls)
                    expected_alias_calls = alias_calls + (1 if name == "discord_call" else 0)
                    self.assertEqual(resolve_discord_contact.call_count, expected_alias_calls)
                    self.assertEqual(with_client_or_launch.call_count, league_calls)
                    completed = await client.confirm(pending[0]["confirmation_id"], True)
                    self.assertEqual(completed[0]["type"], "tool_result")
                    self.assertEqual(completed[0]["tool_name"], name)
                    self.assertNotIn("url", completed[0])
                    self.assertNotIn("phone", completed[0])
                self.assertEqual(open_browser.call_count, 4)
                resolve_discord_contact.assert_called_once_with("amigo")
                self.assertEqual(with_client_or_launch.call_count, 1)
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exercise())
        self.assertEqual(core.sessions.count(), 0)

    def test_v1_message_is_closed_without_downgrade(self):
        core, gateway, _client, _server_identity, _executed = self._build()

        async def exercise():
            gateway.start()
            try:
                reader, writer = await asyncio.open_connection(gateway.bind_host, gateway.port)
                writer.write(b'{"protocol_version":1,"type":"ping"}\n')
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.read(), timeout=2), b"")
                writer.close()
                await writer.wait_closed()
            finally:
                gateway.stop()

        asyncio.run(exercise())
        self.assertEqual(core.sessions.count(), 0)

    def test_wrong_server_pin_closes_the_session(self):
        core, gateway, client, _server_identity, _executed = self._build()
        client.server_public_key = Ed25519PrivateKey.generate().public_key()

        async def exercise():
            gateway.start()
            try:
                with self.assertRaises(ValueError):
                    await client.connect(gateway.bind_host, gateway.port)
                await asyncio.sleep(0.05)
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exercise())
        self.assertEqual(core.sessions.count(), 0)

    def test_client_hello_replay_is_rejected_across_connections(self):
        core, gateway, client, _server_identity, _executed = self._build()
        client_identity = client.identity
        hello, _ephemeral = create_client_hello(client_identity, session_id="replayed-session")
        line = (json.dumps(hello.as_dict(), separators=(",", ":")) + "\n").encode()

        async def exchange():
            gateway.start()
            try:
                _reader, writer = await asyncio.open_connection(gateway.bind_host, gateway.port)
                writer.write(line)
                await writer.drain()
                writer.close()
                await writer.wait_closed()

                reader, writer = await asyncio.open_connection(gateway.bind_host, gateway.port)
                writer.write(line)
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.read(), timeout=2), b"")
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.05)
            finally:
                gateway.stop()

        asyncio.run(exchange())
        self.assertEqual(core.sessions.count(), 0)

    def test_revocation_provider_closes_an_active_session(self):
        core, gateway, client, _server_identity, _executed = self._build()
        trusted = dict(gateway.trusted_devices)
        gateway.trusted_devices_provider = lambda: trusted
        gateway.revocation_check_seconds = 0.1

        async def exchange():
            gateway.start()
            try:
                await client.connect(gateway.bind_host, gateway.port)
                trusted.clear()
                await asyncio.sleep(0.25)
                with self.assertRaises(ValueError):
                    await client.send_text("estado de League")
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exchange())
        self.assertEqual(core.sessions.count(), 0)

    def test_revocation_store_failure_closes_an_active_session(self):
        core, gateway, client, _server_identity, _executed = self._build()
        trusted = dict(gateway.trusted_devices)
        provider_calls = 0

        def provider():
            nonlocal provider_calls
            provider_calls += 1
            if provider_calls == 1:
                return trusted
            raise DeviceStoreError("store detail")

        gateway.trusted_devices_provider = provider
        gateway.revocation_check_seconds = 0.1

        async def exchange():
            gateway.start()
            try:
                await client.connect(gateway.bind_host, gateway.port)
                await asyncio.sleep(0.25)
                with self.assertRaises(ValueError):
                    await client.send_text("estado de League")
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exchange())
        self.assertEqual(core.sessions.count(), 0)

    def test_store_failure_during_handshake_closes_without_creating_a_session(self):
        core, gateway, client, _server_identity, _executed = self._build()
        gateway.trusted_devices_provider = lambda: (_ for _ in ()).throw(DeviceStoreError("store detail"))
        hello, _ephemeral = create_client_hello(client.identity)
        line = (json.dumps(hello.as_dict(), separators=(",", ":")) + "\n").encode()

        async def exchange():
            gateway.start()
            try:
                reader, writer = await asyncio.open_connection(gateway.bind_host, gateway.port)
                writer.write(line)
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.read(), timeout=2), b"")
                writer.close()
                await writer.wait_closed()
            finally:
                gateway.stop()

        asyncio.run(exchange())
        self.assertEqual(core.sessions.count(), 0)

    def test_connection_limit_rejects_an_extra_socket(self):
        core, gateway, client, _server_identity, _executed = self._build()
        gateway.max_connections = 1

        async def exchange():
            gateway.start()
            try:
                await client.connect(gateway.bind_host, gateway.port)
                reader, writer = await asyncio.open_connection(gateway.bind_host, gateway.port)
                self.assertEqual(await asyncio.wait_for(reader.read(), timeout=2), b"")
                writer.close()
                await writer.wait_closed()
            finally:
                await client.close()
                gateway.stop()

        asyncio.run(exchange())
        self.assertEqual(core.sessions.count(), 0)

    def test_bind_validation_rejects_wildcard_and_public_addresses(self):
        self.assertEqual(validate_mobile_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_mobile_bind_host("::1"), "::1")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("0.0.0.0")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("8.8.8.8")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("192.0.0.1")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("198.18.0.1")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("100.64.0.1")
        with self.assertRaises(ValueError):
            validate_mobile_bind_host("fd00::20")

    def test_reference_client_rejects_non_private_hosts_before_connecting(self):
        _core, _gateway, client, _server_identity, _executed = self._build()

        async def exercise():
            with self.assertRaises(ValueError):
                await client.connect("8.8.8.8", 18765)
            with self.assertRaises(ValueError):
                await client.connect("agent.example.com", 18765)

        asyncio.run(exercise())

    @patch.dict("secure_tcp_gateway.os.environ", {}, clear=True)
    def test_mobile_gateway_is_disabled_without_explicit_mode(self):
        core = PipaCore(verifier=object(), router=ToolRouter(ToolCatalog([])))

        self.assertIsNone(start_configured_mobile_gateway(core))

    def test_duplicate_outer_json_fields_are_rejected(self):
        from secure_tcp_gateway import _strict_json

        with self.assertRaises(ValueError):
            _strict_json(b'{"type":"x","type":"y"}')


if __name__ == "__main__":
    unittest.main()
