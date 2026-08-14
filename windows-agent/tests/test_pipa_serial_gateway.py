import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from pipa_serial_gateway import MAX_LINE_BYTES, MAX_PROTOCOL_ERRORS, SerialGateway  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store  # noqa: E402
from trusted_unlock_protocol import Challenge  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402

from backend.pipa_core.connection import (  # noqa: E402
    AUTHENTICATION_TIMEOUT_SECONDS,
    MAX_AUTH_FAILURES,
    AuthenticatedConnection,
)
from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.protocol import parse_client_message  # noqa: E402
from backend.pipa_core.state import SessionLimitError  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402


class FakeSerialConnection:
    def __init__(self, lines, gateway):
        self.lines = list(lines)
        self.gateway = gateway
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

    def reset_input_buffer(self):
        pass


class SerialProtocolSessionTests(unittest.TestCase):
    def setUp(self):
        device = InMemoryTrustedDevice.generate("waveshare-01")
        store = InMemoryDeviceStore()
        store.register(device.device_id, device.public_key)
        self.device = device
        self.core = PipaCore(verifier_from_store(store), ToolRouter(ToolCatalog([])))
        self.now = 100.0
        self.protocol = AuthenticatedConnection(self.core, clock=lambda: self.now)

    def test_challenge_request_then_signed_hello(self):
        challenge = self._request_challenge()
        signed = self.device.sign(Challenge(**challenge))
        hello = parse_client_message(
            {
                "protocol_version": 1,
                "type": "hello",
                "device_id": "waveshare-01",
                "challenge_id": signed.challenge_id,
                "signature": signed.signature,
                "firmware_version": "0.2.0",
                "capabilities": ["touch", "wol"],
            }
        )

        result = self.protocol.process(hello)

        self.assertFalse(result.close)
        self.assertEqual(result.responses[0]["type"], "ready")
        session = self.core.sessions.get(self.protocol.session_id)
        self.assertEqual(session.firmware_version, "0.2.0")
        self.assertEqual(session.capabilities, ("touch", "wol"))

    def test_challenge_requests_are_rate_limited(self):
        self._request_challenge()
        result = self.protocol.process(self._challenge_request("waveshare-01"))
        self.assertEqual(result.responses[0]["code"], "rate_limited")

    def test_unknown_device_is_closed_after_repeated_failures(self):
        for _attempt in range(MAX_AUTH_FAILURES):
            self.now += 2
            result = self.protocol.process(self._challenge_request("unknown-device"))
        self.assertTrue(result.close)
        self.assertEqual(result.responses[0]["code"], "authentication_failed")

    def test_ping_requires_authentication(self):
        result = self.protocol.process(parse_client_message({"protocol_version": 1, "type": "ping"}))
        self.assertEqual(result.responses[0]["code"], "authentication_required")

    def test_unauthenticated_connection_has_a_short_timeout(self):
        self.now += AUTHENTICATION_TIMEOUT_SECONDS
        self.assertTrue(self.protocol.idle())

    def test_gateway_validates_configuration(self):
        with self.assertRaises(ValueError):
            SerialGateway(self.core, "")
        with self.assertRaises(ValueError):
            SerialGateway(self.core, "COM7", baudrate=100)
        with patch("pipa_serial_gateway.platform.system", return_value="Windows"):
            self.assertEqual(SerialGateway(self.core, "com7").port, "COM7")
            with self.assertRaises(ValueError):
                SerialGateway(self.core, r"\\.\COM7")

    def test_gateway_reports_worker_and_port_connection_separately(self):
        gateway = SerialGateway(self.core, "COM7")

        self.assertFalse(gateway.running)
        self.assertFalse(gateway.connected)

        gateway._connected.set()
        self.assertTrue(gateway.connected)
        gateway.stop()
        self.assertFalse(gateway.connected)

    def test_session_limit_is_a_controlled_authentication_error(self):
        challenge = self._request_challenge()
        signed = self.device.sign(Challenge(**challenge))
        hello = parse_client_message(
            {
                "protocol_version": 1,
                "type": "hello",
                "device_id": self.device.device_id,
                "challenge_id": signed.challenge_id,
                "signature": signed.signature,
            }
        )
        with patch.object(self.core.sessions, "create", side_effect=SessionLimitError("full")):
            result = self.protocol.process(hello)

        self.assertTrue(result.close)
        self.assertEqual(result.responses[0]["code"], "session_limit")

    def test_idle_connection_and_close_are_fail_closed(self):
        challenge = self._request_challenge()
        signed = self.device.sign(Challenge(**challenge))
        self.protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "hello",
                    "device_id": self.device.device_id,
                    "challenge_id": signed.challenge_id,
                    "signature": signed.signature,
                }
            )
        )
        self.assertEqual(self.core.sessions.count(), 1)
        self.now += 600
        self.assertTrue(self.protocol.idle())

        self.protocol.close()

        self.assertEqual(self.core.sessions.count(), 0)

    def test_serial_diagnostics_do_not_poison_json_framing(self):
        gateway = SerialGateway(self.core, "COM7")
        request = (
            json.dumps(
                {"protocol_version": 1, "type": "challenge_request", "device_id": "waveshare-01"}
            ).encode("utf-8")
            + b"\n"
        )
        connection = FakeSerialConnection([b"# boot diagnostic\n", request], gateway)

        gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), 1)
        response = json.loads(connection.writes[0].decode("utf-8"))
        self.assertEqual(response["type"], "challenge")

    def test_repeated_invalid_serial_messages_close_without_reflecting_input(self):
        gateway = SerialGateway(self.core, "COM7")
        malicious = b'{"type":"' + (b"x" * 4000) + b'"}\n'
        connection = FakeSerialConnection([malicious] * MAX_PROTOCOL_ERRORS, gateway)

        gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), MAX_PROTOCOL_ERRORS)
        for raw in connection.writes:
            response = json.loads(raw.decode("utf-8"))
            self.assertEqual(response["code"], "protocol_error")
            self.assertNotIn("x" * 100, raw.decode("utf-8"))

    def test_duplicate_serial_json_fields_are_rejected(self):
        gateway = SerialGateway(self.core, "COM7")
        duplicate = b'{"protocol_version":1,"type":"challenge_request","type":"ping"}\n'
        connection = FakeSerialConnection([duplicate], gateway)

        gateway._serve_connection(connection)

        self.assertEqual(len(connection.writes), 1)
        response = json.loads(connection.writes[0].decode("utf-8"))
        self.assertEqual(response["code"], "protocol_error")

    def test_oversized_serial_responses_are_replaced_by_a_bounded_error(self):
        gateway = SerialGateway(self.core, "COM7")
        connection = FakeSerialConnection([], gateway)

        gateway._send(connection, {"type": "result", "data": "x" * MAX_LINE_BYTES})

        self.assertEqual(len(connection.writes), 1)
        self.assertLessEqual(len(connection.writes[0]), MAX_LINE_BYTES)
        response = json.loads(connection.writes[0].decode("utf-8"))
        self.assertEqual(response["code"], "response_too_large")

    def test_authenticated_serial_flow_requires_and_resolves_confirmation(self):
        executed = []

        def handler(arguments):
            executed.append(arguments)
            return {"success": True, "private_value": arguments["value"]}

        catalog = ToolCatalog(
            [
                ToolDefinition(
                    "external_action",
                    handler,
                    safety="unsafe",
                    confirm_summary=lambda _arguments: "Ejecutar acción externa",
                )
            ]
        )
        core = PipaCore(self.core.verifier, ToolRouter(catalog))
        protocol = AuthenticatedConnection(core, clock=lambda: self.now)

        challenge = protocol.process(self._challenge_request("waveshare-01")).responses[0]["challenge"]
        signed = self.device.sign(Challenge(**challenge))
        ready = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "hello",
                    "device_id": self.device.device_id,
                    "challenge_id": signed.challenge_id,
                    "signature": signed.signature,
                    "capabilities": ["display", "touch"],
                }
            )
        )
        self.assertEqual(ready.responses[0]["type"], "ready")

        pending = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "tool_call",
                    "name": "external_action",
                    "arguments": {"value": "only-after-confirmation"},
                }
            )
        )
        request = pending.responses[0]
        self.assertEqual(request["type"], "confirm_request")
        self.assertEqual(executed, [])

        completed = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "confirm",
                    "confirmation_id": request["confirmation_id"],
                    "accepted": True,
                }
            )
        )
        self.assertEqual(completed.responses[0]["type"], "tool_result")
        self.assertTrue(completed.responses[0]["success"])
        self.assertNotIn("result", completed.responses[0])
        self.assertNotIn("only-after-confirmation", str(completed.responses[0]))
        self.assertEqual(executed, [{"value": "only-after-confirmation"}])
        self.assertEqual(completed.responses[1]["state"], "idle")

    def _request_challenge(self):
        result = self.protocol.process(self._challenge_request("waveshare-01"))
        self.assertFalse(result.close)
        return result.responses[0]["challenge"]

    @staticmethod
    def _challenge_request(device_id):
        return parse_client_message(
            {"protocol_version": 1, "type": "challenge_request", "device_id": device_id}
        )


if __name__ == "__main__":
    unittest.main()
