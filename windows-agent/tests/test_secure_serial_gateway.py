import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_audio import SecureAudioSender  # noqa: E402
from secure_identity_store import SecureIdentityStoreError  # noqa: E402
from secure_json_channel import SecureJsonChannel  # noqa: E402
from secure_serial_gateway import (  # noqa: E402
    SecureSerialGateway,
    _strict_json,
    start_configured_secure_gateway,
)
from secure_session import (  # noqa: E402
    SecureIdentity,
    ServerHello,
    complete_client_handshake,
    create_client_hello,
)
from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.timers import TimerManager  # noqa: E402

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolRouter  # noqa: E402


class FakeSecureSerialConnection:
    def __init__(self, lines, gateway, on_write=None):
        self.lines = list(lines)
        self.gateway = gateway
        self.on_write = on_write
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read_until(self, _separator, _size):
        if self.lines:
            return self.lines.pop(0)
        self.gateway._stop.set()
        return b""

    def write(self, value):
        self.writes.append(value)
        if self.on_write is not None:
            self.on_write(value)

    def reset_input_buffer(self):
        pass


class SecureSerialGatewayTests(unittest.TestCase):
    def setUp(self):
        self.client_identity = SecureIdentity("waveshare-v2", Ed25519PrivateKey.generate())
        self.server_identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        self.core = PipaCore(verifier=object(), router=ToolRouter(ToolCatalog([])))
        self.gateway = SecureSerialGateway(
            self.core,
            "COM7",
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )

    def test_secure_gateway_round_trips_encrypted_ping_without_v1_fallback(self):
        client_hello, client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="serial-session",
        )
        client_channel = None

        def append_encrypted_request(value):
            nonlocal client_channel
            if len(connection.writes) != 1:
                return
            server_payload = json.loads(value.decode("utf-8"))
            client_session = complete_client_handshake(
                self.client_identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                self.server_identity.public_key,
            )
            client_channel = SecureJsonChannel(client_session)
            connection.lines.append(
                json.dumps(
                    client_channel.seal_message(
                        {"protocol_version": 1, "type": "ping", "request_id": "secure"}
                    )
                ).encode()
                + b"\n"
            )

        encoded_hello = json.dumps(client_hello.as_dict()).encode() + b"\n"
        connection = FakeSecureSerialConnection(
            [b"[ 123][W][driver.cpp:1] bounded diagnostic\n", encoded_hello[:1], encoded_hello[1:]],
            self.gateway,
            on_write=append_encrypted_request,
        )
        self.gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), 2)
        returned_server_hello = json.loads(connection.writes[0].decode("utf-8"))
        self.assertEqual(returned_server_hello["server_id"], self.server_identity.identity_id)
        response_frame = json.loads(connection.writes[1].decode("utf-8"))
        self.assertIsNotNone(client_channel)
        self.assertEqual(client_channel.open_message(response_frame)["type"], "pong")

    def test_secure_gateway_transcribes_an_authenticated_audio_stream(self):
        class FakeSpeechProvider:
            diagnostics = {
                "model": "base",
                "peak_dbfs": -16.5,
                "speech_duration_ms": 1300,
            }

            def __call__(self, _samples, final):
                return "una frase que no existe" if final else None

            def reset(self):
                pass

        gateway = SecureSerialGateway(
            self.core,
            "COM7",
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
            speech_provider_factory=FakeSpeechProvider,
        )
        client_hello, client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="secure-audio-serial",
        )
        client_channel = None
        received = []

        def continue_exchange(value):
            nonlocal client_channel
            payload = json.loads(value.decode("utf-8"))
            if len(connection.writes) == 1:
                client_session = complete_client_handshake(
                    self.client_identity,
                    client_hello,
                    client_ephemeral,
                    ServerHello(**payload),
                    self.server_identity.public_key,
                )
                client_channel = SecureJsonChannel(client_session)
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message(
                            {
                                "protocol_version": 1,
                                "type": "device_hello",
                                "firmware_version": "voice-test",
                                "capabilities": [
                                    "display",
                                    "touch",
                                    "audio_capture",
                                    "local_wake_phrase",
                                ],
                            }
                        )
                    ).encode()
                    + b"\n"
                )
                return

            assert client_channel is not None
            message = client_channel.open_message(payload)
            received.append(message)
            if message["type"] == "device_hello_ack":
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message(
                            {
                                "protocol_version": 1,
                                "type": "device_status",
                                "audio_state": "codec_ready",
                            }
                        )
                    ).encode()
                    + b"\n"
                )
            elif message["type"] == "status_ack":
                self.assertTrue(gateway.voice_ready)
                self.assertTrue(gateway.local_wake_phrase_ready)
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message({"protocol_version": 1, "type": "hold_start"})
                    ).encode()
                    + b"\n"
                )
            elif message["type"] == "ui_state" and message["state"] == "listening":
                audio_sender = SecureAudioSender(client_channel.session, "voice-test")
                frame = audio_sender.seal_chunk(b"\x01\x02" * 2000, final=True)
                connection.lines.append(json.dumps(frame).encode() + b"\n")

        connection = FakeSecureSerialConnection(
            [json.dumps(client_hello.as_dict()).encode() + b"\n"],
            gateway,
            on_write=continue_exchange,
        )
        gateway._serve_connection(connection)

        self.assertTrue(any(message.get("code") == "unsupported_text_intent" for message in received))
        self.assertTrue(any(message.get("state") == "idle" for message in received))
        self.assertFalse(gateway.voice_ready)
        self.assertFalse(gateway.local_wake_phrase_ready)
        self.assertEqual(self.core.sessions.count(), 0)
        diagnostic = gateway.voice_diagnostics()
        self.assertTrue(diagnostic["available"])
        self.assertFalse(diagnostic["recognized"])
        self.assertEqual(diagnostic["transcript"], "una frase que no existe")
        self.assertEqual(diagnostic["error_code"], "unsupported_text_intent")
        self.assertEqual(diagnostic["stt"]["peak_dbfs"], -16.5)

    @patch("webbrowser.open", return_value=True)
    @patch("tools.agent_catalog.resolve_discord_contact")
    @patch("tools.agent_catalog.with_client_or_launch")
    def test_secure_gateway_runs_external_integrations_only_after_touch_confirmation(
        self,
        with_client_or_launch,
        resolve_discord_contact,
        open_browser,
    ):
        """Exercise the physical-device path for the five guarded integrations.

        The fake serial connection still uses the real encrypted record layer,
        Core, intent/tool router and adapters. Only browser launching, the
        Discord alias and the League client are replaced by deterministic
        in-memory fakes. This proves that a secure session announces physical
        confirmation capabilities before any external action can run.
        """

        class FakeLeagueClient:
            def start_search(self, queue):
                return {"started": True, "queue": queue}

        fake_league = FakeLeagueClient()
        with_client_or_launch.side_effect = lambda callback, _launcher: callback(fake_league)
        resolve_discord_contact.return_value = ("amigo", "12345678901234567", None)
        actions = [
            ("web_search", {"query": "documentación de Pipa"}),
            ("music_search", {"term": "Daft Punk"}),
            ("whatsapp_compose", {"phone": "+34600123456", "message": "mensaje de prueba"}),
            ("discord_call", {"contact": "amigo"}),
            ("league_search", {"queue": "normal_draft"}),
        ]
        core = PipaCore(
            verifier=object(),
            router=ToolRouter(build_agent_catalog(TimerManager())),
        )
        gateway = SecureSerialGateway(
            core,
            "COM7",
            self.server_identity,
            {self.client_identity.identity_id: self.client_identity.public_key},
        )
        client_hello, client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="secure-integrations",
        )
        client_channel = None
        server_messages = []
        action_index = 0

        def append_next_client_frame(value):
            nonlocal client_channel, action_index
            server_payload = json.loads(value.decode("utf-8"))
            if len(connection.writes) == 1:
                client_session = complete_client_handshake(
                    self.client_identity,
                    client_hello,
                    client_ephemeral,
                    ServerHello(**server_payload),
                    self.server_identity.public_key,
                )
                client_channel = SecureJsonChannel(client_session)
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message(
                            {
                                "protocol_version": 1,
                                "type": "device_hello",
                                "firmware_version": "test-device",
                                "capabilities": ["display", "touch", "text_input"],
                            }
                        )
                    ).encode()
                    + b"\n"
                )
                return

            assert client_channel is not None
            message = client_channel.open_message(server_payload)
            server_messages.append(message)
            if message["type"] == "device_hello_ack":
                name, arguments = actions[action_index]
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message(
                            {
                                "protocol_version": 1,
                                "type": "tool_call",
                                "name": name,
                                "arguments": arguments,
                                "call_id": f"integration-{action_index}",
                            }
                        )
                    ).encode()
                    + b"\n"
                )
            elif message["type"] == "confirm_request":
                connection.lines.append(
                    json.dumps(
                        client_channel.seal_message(
                            {
                                "protocol_version": 1,
                                "type": "confirm",
                                "confirmation_id": message["confirmation_id"],
                                "accepted": True,
                            }
                        )
                    ).encode()
                    + b"\n"
                )
            elif message["type"] == "tool_result":
                action_index += 1
                if action_index < len(actions):
                    name, arguments = actions[action_index]
                    connection.lines.append(
                        json.dumps(
                            client_channel.seal_message(
                                {
                                    "protocol_version": 1,
                                    "type": "tool_call",
                                    "name": name,
                                    "arguments": arguments,
                                    "call_id": f"integration-{action_index}",
                                }
                            )
                        ).encode()
                        + b"\n"
                    )

        connection = FakeSecureSerialConnection(
            [json.dumps(client_hello.as_dict()).encode() + b"\n"],
            gateway,
            on_write=append_next_client_frame,
        )
        gateway._serve_connection(connection)

        confirm_requests = [item for item in server_messages if item["type"] == "confirm_request"]
        results = [item for item in server_messages if item["type"] == "tool_result"]
        self.assertEqual(len(confirm_requests), len(actions))
        self.assertEqual([item["tool_name"] for item in confirm_requests], [item[0] for item in actions])
        self.assertEqual([item["tool_name"] for item in results], [item[0] for item in actions])
        self.assertTrue(all(item["success"] for item in results))
        self.assertTrue(
            all(item["summary"].startswith(("Buscar", "Preparar", "Abrir")) for item in confirm_requests)
        )
        self.assertNotIn("600123456", str(confirm_requests))
        self.assertNotIn("mensaje de prueba", str(confirm_requests))
        self.assertTrue(all("url" not in item and "phone" not in item for item in results))
        self.assertEqual(open_browser.call_count, 4)
        resolve_discord_contact.assert_called_once_with("amigo")
        with_client_or_launch.assert_called_once()

    def test_secure_gateway_rejects_v1_message_instead_of_downgrading(self):
        connection = FakeSecureSerialConnection(
            [b'{"protocol_version":1,"type":"ping"}\n'],
            self.gateway,
        )

        self.gateway._serve_connection(connection)

        self.assertEqual(connection.writes, [])
        self.assertEqual(self.core.sessions.count(), 0)

    def test_secure_gateway_requests_a_new_handshake_after_agent_restart(self):
        client_hello, _client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="restarted-agent",
        )

        def restart_device_handshake(value):
            payload = json.loads(value.decode("utf-8"))
            if payload.get("type") == "session_reset":
                connection.lines.append(json.dumps(client_hello.as_dict()).encode() + b"\n")

        stale_frame = {
            "ciphertext": "old-session-record",
            "protocol_version": 2,
            "sequence": 7,
            "session_id": "old-session",
        }
        connection = FakeSecureSerialConnection(
            [json.dumps(stale_frame).encode() + b"\n"],
            self.gateway,
            on_write=restart_device_handshake,
        )

        self.gateway._serve_connection(connection)

        self.assertEqual(json.loads(connection.writes[0]), {"protocol_version": 2, "type": "session_reset"})
        self.assertEqual(json.loads(connection.writes[1])["server_id"], self.server_identity.identity_id)
        self.assertEqual(self.core.sessions.count(), 0)

    @patch("secure_serial_gateway.AUTHENTICATION_TIMEOUT_SECONDS", 0)
    def test_secure_gateway_closes_an_unauthenticated_idle_connection(self):
        connection = FakeSecureSerialConnection([], self.gateway)

        self.gateway._serve_connection(connection)

        self.assertEqual(connection.writes, [])

    def test_secure_gateway_rejects_v1_after_the_handshake(self):
        client_hello, _client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="no-downgrade",
        )
        connection = FakeSecureSerialConnection(
            [
                json.dumps(client_hello.as_dict()).encode() + b"\n",
                b'{"protocol_version":1,"type":"ping"}\n',
            ],
            self.gateway,
        )

        self.gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), 1)
        self.assertEqual(self.core.sessions.count(), 0)

    @patch("secure_serial_gateway.DEFAULT_REVOCATION_CHECK_SECONDS", 0.1)
    def test_secure_gateway_closes_a_session_after_revocation(self):
        current_devices = {self.client_identity.identity_id: self.client_identity.public_key}
        gateway = SecureSerialGateway(
            self.core,
            "COM7",
            self.server_identity,
            current_devices,
            trusted_devices_provider=lambda: current_devices,
            revocation_check_seconds=0.1,
        )
        client_hello, client_ephemeral = create_client_hello(
            self.client_identity,
            session_id="revoked-session",
        )

        def revoke_after_server_hello(value):
            if len(connection.writes) != 1:
                return
            current_devices.clear()
            server_payload = json.loads(value.decode("utf-8"))
            client_session = complete_client_handshake(
                self.client_identity,
                client_hello,
                client_ephemeral,
                ServerHello(**server_payload),
                self.server_identity.public_key,
            )
            connection.lines.append(
                json.dumps(
                    SecureJsonChannel(client_session).seal_message(
                        {"protocol_version": 1, "type": "ping", "request_id": "revoked"}
                    )
                ).encode()
                + b"\n"
            )

        connection = FakeSecureSerialConnection(
            [json.dumps(client_hello.as_dict()).encode() + b"\n"],
            gateway,
            on_write=revoke_after_server_hello,
        )
        gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), 1)
        self.assertEqual(self.core.sessions.count(), 0)

    def test_duplicate_outer_json_fields_fail_closed(self):
        with self.assertRaises(ValueError):
            _strict_json('{"protocol_version":2,"protocol_version":1}')

    def test_oversized_secure_response_does_not_emit_a_v1_error(self):
        connection = FakeSecureSerialConnection([], self.gateway)

        SecureSerialGateway._send(connection, {"ciphertext": "x" * 12000})

        self.assertEqual(connection.writes, [])

    @patch.dict(
        "secure_serial_gateway.os.environ",
        {"PIPA_SERIAL_PORT": "COM7", "PIPA_SERIAL_SECURITY": "unsupported"},
        clear=True,
    )
    def test_unknown_security_mode_disables_the_default_gateway(self):
        from pipa_serial_gateway import start_configured_gateway

        self.assertIsNone(start_configured_gateway(self.core))

    @patch.dict(
        "secure_serial_gateway.os.environ",
        {"PIPA_SERIAL_PORT": "COM7", "PIPA_SECURE_SERVER_ID": "pipa-agent-v2"},
        clear=True,
    )
    @patch("secure_serial_gateway.default_secure_identity_path", return_value=Path("identity.json"))
    @patch("secure_serial_gateway.SecureIdentityStore")
    def test_secure_gateway_never_creates_identity_at_startup(
        self,
        identity_store_class,
        _identity_path,
    ):
        identity_store_class.return_value.load.side_effect = SecureIdentityStoreError("missing")

        self.assertIsNone(start_configured_secure_gateway(self.core))
        identity_store_class.return_value.load.assert_called_once_with("pipa-agent-v2")
        identity_store_class.return_value.load_or_create.assert_not_called()

    @patch.dict(
        "secure_serial_gateway.os.environ",
        {"PIPA_SERIAL_PORT": "COM7", "PIPA_SECURE_SERVER_ID": "pipa-agent-v2"},
        clear=True,
    )
    @patch("secure_serial_gateway.WindowsRegistryDeviceStore")
    @patch("secure_serial_gateway.default_secure_identity_path", return_value=Path("identity.json"))
    @patch("secure_serial_gateway.SecureIdentityStore")
    def test_secure_gateway_does_not_start_without_a_paired_device(
        self,
        identity_store_class,
        _identity_path,
        device_store_class,
    ):
        identity_store_class.return_value.load.return_value = self.server_identity
        device_store_class.return_value.trusted_public_keys.return_value = {}

        self.assertIsNone(start_configured_secure_gateway(self.core))
        device_store_class.return_value.trusted_public_keys.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
