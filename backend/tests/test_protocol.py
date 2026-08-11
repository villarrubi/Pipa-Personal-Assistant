import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from backend.pipa_core.protocol import ProtocolError, parse_client_message  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_parses_challenge_request(self):
        message = parse_client_message(
            {"protocol_version": 1, "type": "challenge_request", "device_id": "waveshare-01"}
        )
        self.assertEqual(message.type, "challenge_request")
        self.assertEqual(message.fields["device_id"], "waveshare-01")

    def test_parses_tool_call(self):
        message = parse_client_message(
            {
                "protocol_version": 1,
                "type": "tool_call",
                "name": "media_action",
                "arguments": {"action": "play_pause"},
            }
        )
        self.assertEqual(message.type, "tool_call")
        self.assertEqual(message.fields["arguments"]["action"], "play_pause")

    def test_rejects_unknown_version(self):
        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 2, "type": "wake"})

    def test_requires_confirmation_boolean(self):
        with self.assertRaises(ProtocolError):
            parse_client_message(
                {"protocol_version": 1, "type": "confirm", "confirmation_id": "x", "accepted": "yes"}
            )


if __name__ == "__main__":
    unittest.main()
