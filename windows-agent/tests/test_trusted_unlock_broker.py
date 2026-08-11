import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trusted_unlock_broker import TrustedUnlockBroker  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402


class TrustedUnlockBrokerTests(unittest.TestCase):
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

    def test_health_advertises_unlock_is_disabled(self):
        response = self.request("health")

        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["unlock_enabled"])

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
        ticket = submit_response["result"]["ticket"]
        consumed = self.request("ticket.consume", {"token": ticket["token"]})

        self.assertTrue(consumed["ok"])
        self.assertTrue(consumed["result"]["consumed"])
        self.assertFalse(consumed["result"]["unlock_enabled"])

        replay = self.request("ticket.consume", {"token": ticket["token"]})
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["error"]["code"], "ticket_replay")

    def test_unknown_device_is_rejected(self):
        response = self.request("challenge.create", {"device_id": "unknown"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unknown_device")

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
