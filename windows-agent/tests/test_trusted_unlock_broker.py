import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_broker import (  # noqa: E402
    FILE_FLAG_FIRST_PIPE_INSTANCE,
    TrustedUnlockBroker,
)
from trusted_unlock_broker_client import (  # noqa: E402
    BrokerClientError,
    WindowsNamedPipeBrokerClient,
    _decode_response,
)
from trusted_unlock_devices import InMemoryDeviceStore  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402


class TrustedUnlockBrokerTests(unittest.TestCase):
    def test_broker_client_rejects_non_local_pipe_names(self):
        with self.assertRaises(ValueError):
            WindowsNamedPipeBrokerClient(pipe_name=r"\\server\pipe\PipaTrustedUnlock")

    def test_broker_client_rejects_duplicate_response_fields(self):
        raw_response = b'{"ok":true,"request_id":"request-1","request_id":"other","result":{}}'

        with self.assertRaises(BrokerClientError) as context:
            _decode_response(raw_response, "request-1")

        self.assertEqual(context.exception.code, "invalid_response")

    def test_broker_client_rejects_unknown_response_fields(self):
        raw_response = b'{"ok":true,"request_id":"request-1","result":{},"extra":true}'

        with self.assertRaises(BrokerClientError) as context:
            _decode_response(raw_response, "request-1")

        self.assertEqual(context.exception.code, "invalid_response")

    def test_broker_client_accepts_only_structured_broker_errors(self):
        raw_response = (
            '{"ok":false,"request_id":"request-1",'
            '"error":{"code":"authorization_failed","message":"Autorización rechazada."}}'
        ).encode()

        with self.assertRaises(BrokerClientError) as context:
            _decode_response(raw_response, "request-1")

        self.assertEqual(context.exception.code, "authorization_failed")
        self.assertEqual(context.exception.message, "Autorización rechazada.")

        malformed_error = (
            b'{"ok":false,"request_id":"request-1",'
            b'"error":{"code":"authorization_failed","message":"ok","extra":true}}'
        )
        with self.assertRaises(BrokerClientError) as malformed_context:
            _decode_response(malformed_error, "request-1")
        self.assertEqual(malformed_context.exception.code, "invalid_response")

    def test_broker_client_bounds_the_complete_named_pipe_exchange(self):
        calls = []

        class FakePywinError(Exception):
            pass

        pywintypes = types.ModuleType("pywintypes")
        pywintypes.error = FakePywinError
        win32pipe = types.ModuleType("win32pipe")

        def call_named_pipe(pipe_name, encoded_request, output_size, timeout_ms):
            request = json.loads(encoded_request.decode("utf-8"))
            calls.append((pipe_name, output_size, timeout_ms))
            return json.dumps(
                {
                    "ok": True,
                    "request_id": request["request_id"],
                    "result": {"unlock_enabled": False},
                },
                separators=(",", ":"),
            ).encode("utf-8")

        win32pipe.CallNamedPipe = call_named_pipe
        with patch.dict(sys.modules, {"pywintypes": pywintypes, "win32pipe": win32pipe}):
            result = WindowsNamedPipeBrokerClient(timeout_ms=234).request("health")

        self.assertEqual(result, {"unlock_enabled": False})
        self.assertEqual(calls, [(r"\\.\pipe\PipaTrustedUnlock", 16 * 1024 + 1, 234)])

    def setUp(self):
        self.device = InMemoryTrustedDevice.generate("phone-main")
        store = InMemoryDeviceStore()
        store.register("phone-main", self.device.public_key, created_at=1000)
        self.broker = TrustedUnlockBroker.from_store(store)

    def request(self, command, payload=None):
        response = self.broker.handle_request(
            {
                "version": 1,
                "request_id": "test-request",
                "command": command,
                "payload": payload or {},
            }
        )
        return response

    def assert_no_windows_credential_payload(self, result):
        forbidden_keys = {
            "credential",
            "password",
            "pin",
            "secret",
            "serialization",
            "username",
        }
        self.assertTrue(forbidden_keys.isdisjoint(result))

    def test_health_advertises_unlock_is_disabled(self):
        response = self.request("health")

        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["unlock_enabled"])

    def test_broker_protocol_rejects_unknown_and_duplicate_fields(self):
        unknown = self.broker.handle_request(
            {
                "version": 1,
                "request_id": "test-request",
                "command": "health",
                "payload": {},
                "extra": True,
            }
        )
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error"]["code"], "invalid_request")

        duplicate = self.broker.handle_bytes(
            b'{"version":1,"request_id":"test-request","request_id":"other","command":"health","payload":{}}'
        )
        duplicate_response = json.loads(duplicate.decode("utf-8"))
        self.assertFalse(duplicate_response["ok"])
        self.assertEqual(duplicate_response["error"]["code"], "invalid_request")

    def test_broker_rejects_unicode_formatting_in_structural_fields(self):
        response = self.broker.handle_request(
            {
                "version": 1,
                "request_id": "test\u202e-request",
                "command": "health",
                "payload": {},
            }
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")

        response = self.request("challenge.create", {"device_id": "phone\u202e-main"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")

    def test_named_pipe_requires_first_instance_flag(self):
        self.assertNotEqual(FILE_FLAG_FIRST_PIPE_INSTANCE, 0)

    def test_disabled_broker_never_creates_or_consumes_authorization_state(self):
        for command, payload in (
            ("challenge.create", {"device_id": "phone-main", "ttl_seconds": 30}),
            (
                "challenge.submit",
                {
                    "response": {
                        "challenge_id": "challenge-1",
                        "device_id": "phone-main",
                        "signature": "A" * 86,
                    }
                },
            ),
            ("ticket.consume", {"token": "opaque-token"}),
        ):
            response = self.request(command, payload)
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "unlock_disabled")
            self.assertEqual(response["error"]["message"], "Trusted Unlock está desactivado.")

        health = self.request("health")
        self.assertEqual(health["result"]["pending_challenges"], 0)
        self.assertEqual(health["result"]["pending_tickets"], 0)

    def test_unknown_device_is_rejected(self):
        response = self.request("challenge.create", {"device_id": "unknown"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unlock_disabled")
        self.assertEqual(response["error"]["message"], "Trusted Unlock está desactivado.")
        self.assertNotIn("unknown", response["error"]["message"])

    def test_disabled_authorization_does_not_echo_supplied_values(self):
        response = self.request(
            "challenge.submit",
            {
                "response": {
                    "challenge_id": "challenge-1",
                    "device_id": "phone-main",
                    "signature": "A" * 86,
                }
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unlock_disabled")
        self.assertEqual(response["error"]["message"], "Trusted Unlock está desactivado.")
        self.assertNotIn("phone-main", json.dumps(response))
        self.assertNotIn("A" * 32, json.dumps(response))

    def test_unknown_ticket_does_not_echo_the_supplied_token(self):
        candidate = "opaque-case-value-123"
        response = self.request("ticket.consume", {"token": candidate})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unlock_disabled")
        self.assertEqual(response["error"]["message"], "Trusted Unlock está desactivado.")
        self.assertNotIn(candidate, json.dumps(response))

    def test_malformed_wire_request_is_bounded_and_safe(self):
        response = json.loads(self.broker.handle_bytes(b"not-json").decode("utf-8"))

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")

    def test_oversized_wire_request_is_rejected(self):
        response = json.loads(self.broker.handle_bytes(b"x" * (16 * 1024 + 1)).decode("utf-8"))

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")

    def test_unlock_command_does_not_exist(self):
        response = self.request("unlock.execute")

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
