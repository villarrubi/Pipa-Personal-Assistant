import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from backend.pipa_core.protocol import ProtocolError, parse_client_message, server_message  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_parses_challenge_request(self):
        message = parse_client_message(
            {"protocol_version": 1, "type": "challenge_request", "device_id": "waveshare-01"}
        )
        self.assertEqual(message.type, "challenge_request")
        self.assertEqual(message.fields["device_id"], "waveshare-01")

    def test_parses_device_metadata(self):
        message = parse_client_message(
            {
                "protocol_version": 1,
                "type": "hello",
                "device_id": "waveshare-01",
                "challenge_id": "challenge",
                "signature": "signature",
                "firmware_version": "0.2.0",
                "capabilities": ["touch", "wol"],
            }
        )
        self.assertEqual(message.fields["firmware_version"], "0.2.0")
        self.assertEqual(message.fields["capabilities"], ["touch", "wol"])

    def test_parses_encrypted_device_metadata_announcement(self):
        message = parse_client_message(
            {
                "protocol_version": 1,
                "type": "device_hello",
                "firmware_version": "0.2.0",
                "capabilities": ["display", "touch"],
            }
        )

        self.assertEqual(message.fields["firmware_version"], "0.2.0")
        self.assertEqual(message.fields["capabilities"], ["display", "touch"])

    def test_rejects_duplicate_capabilities(self):
        with self.assertRaises(ProtocolError):
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "hello",
                    "device_id": "waveshare-01",
                    "challenge_id": "challenge",
                    "signature": "signature",
                    "capabilities": ["touch", "touch"],
                }
            )

    def test_capabilities_reject_control_characters(self):
        with self.assertRaises(ProtocolError):
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "device_hello",
                    "capabilities": ["display\n"],
                }
            )

    def test_validates_device_status_ranges(self):
        message = parse_client_message(
            {
                "protocol_version": 1,
                "type": "device_status",
                "audio_state": "probe_only",
                "battery_percent": 80,
                "wifi_rssi": -55,
            }
        )
        self.assertEqual(message.fields["audio_state"], "probe_only")
        self.assertEqual(message.fields["wifi_rssi"], -55)
        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 1, "type": "device_status", "battery_percent": 101})

    def test_rejects_unknown_audio_diagnostic_state(self):
        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 1, "type": "device_status", "audio_state": "capturing"})

    def test_text_input_has_a_bounded_source(self):
        message = parse_client_message(
            {"protocol_version": 1, "type": "text_input", "text": "pausa", "source": "voice"}
        )
        self.assertEqual(message.fields["source"], "voice")
        with self.assertRaises(ProtocolError):
            parse_client_message(
                {"protocol_version": 1, "type": "text_input", "text": "pausa", "source": "remote-shell"}
            )

    def test_catalog_request_has_no_extra_fields(self):
        message = parse_client_message({"protocol_version": 1, "type": "catalog_request"})

        self.assertEqual(message.type, "catalog_request")

        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 1, "type": "catalog_request", "query": "private"})

    def test_text_source_must_be_string(self):
        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 1, "type": "text_input", "text": "hola", "source": []})

    def test_text_fields_reject_control_characters_at_the_protocol_boundary(self):
        for text in ("hola\ncomando", "hola\x00comando", "hola\x7fcomando"):
            with self.subTest(text=repr(text)):
                with self.assertRaises(ProtocolError):
                    parse_client_message(
                        {"protocol_version": 1, "type": "text_input", "text": text, "source": "mobile"}
                    )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_client_message({"protocol_version": 1, "type": "ping", "unexpected": "value"})

    def test_server_message_reserved_fields_cannot_be_overridden(self):
        with self.assertRaises(ValueError):
            server_message("ready", protocol_version=99)

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

    def test_tool_arguments_have_a_bounded_json_size(self):
        with self.assertRaises(ProtocolError):
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "tool_call",
                    "name": "open_url",
                    "arguments": {"url": "x" * 5000},
                }
            )


if __name__ == "__main__":
    unittest.main()
