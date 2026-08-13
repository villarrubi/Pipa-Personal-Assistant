import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_broker import (  # noqa: E402
    FILE_FLAG_FIRST_PIPE_INSTANCE,
    TrustedUnlockBroker,
)
from trusted_unlock_broker_client import WindowsNamedPipeBrokerClient  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402


class TrustedUnlockBrokerTests(unittest.TestCase):
    def test_broker_client_rejects_non_local_pipe_names(self):
        with self.assertRaises(ValueError):
            WindowsNamedPipeBrokerClient(pipe_name=r"\\server\pipe\PipaTrustedUnlock")

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

    def test_authenticated_flow_issues_and_consumes_one_use_ticket(self):
        challenge_response = self.request(
            "challenge.create",
            {"device_id": "phone-main", "ttl_seconds": 30},
        )
        challenge_data = challenge_response["result"]["challenge"]

        from trusted_unlock_protocol import Challenge

        challenge = Challenge(**challenge_data)
        signed = self.device.sign(challenge)
        submit_response = self.request(
            "challenge.submit",
            {
                "response": {
                    "challenge_id": signed.challenge_id,
                    "device_id": signed.device_id,
                    "signature": signed.signature,
                }
            },
        )

        self.assertTrue(submit_response["ok"])
        self.assertFalse(submit_response["result"]["unlock_enabled"])
        self.assert_no_windows_credential_payload(submit_response["result"])
        ticket = submit_response["result"]["ticket"]
        consumed = self.request("ticket.consume", {"token": ticket["token"]})

        self.assertTrue(consumed["ok"])
        self.assertTrue(consumed["result"]["consumed"])
        self.assertFalse(consumed["result"]["unlock_enabled"])
        self.assert_no_windows_credential_payload(consumed["result"])

        replay = self.request("ticket.consume", {"token": ticket["token"]})
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["error"]["code"], "ticket_replay")

    def test_unknown_device_is_rejected(self):
        response = self.request("challenge.create", {"device_id": "unknown"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unknown_device")
        self.assertEqual(response["error"]["message"], "Autorización rechazada.")
        self.assertNotIn("unknown", response["error"]["message"])

    def test_invalid_signature_does_not_echo_device_or_signature(self):
        challenge_response = self.request(
            "challenge.create",
            {"device_id": "phone-main", "ttl_seconds": 30},
        )
        challenge = challenge_response["result"]["challenge"]
        response = self.request(
            "challenge.submit",
            {
                "response": {
                    "challenge_id": challenge["challenge_id"],
                    "device_id": "phone-main",
                    "signature": base64.urlsafe_b64encode(b"invalid-signature".ljust(64, b"!"))
                    .decode("ascii")
                    .rstrip("="),
                }
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_response")
        self.assertEqual(response["error"]["message"], "Autorización rechazada.")
        self.assertNotIn("phone-main", json.dumps(response))
        self.assertNotIn("A" * 32, json.dumps(response))

    def test_unknown_ticket_does_not_echo_the_supplied_token(self):
        candidate = "opaque-case-value-123"
        response = self.request("ticket.consume", {"token": candidate})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unknown_ticket")
        self.assertEqual(response["error"]["message"], "Autorización rechazada.")
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
