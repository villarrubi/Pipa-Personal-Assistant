import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from tools.integration_diagnostics import run_integration_self_test  # noqa: E402
from tools.secure_diagnostics import (  # noqa: E402
    preview_secure_audio_transcript,
    run_mobile_protocol_self_test,
    run_mobile_tcp_self_test,
    run_secure_audio_self_test,
    run_secure_self_test,
)


class SecureDiagnosticsTests(unittest.TestCase):
    def test_integration_self_test_is_inert_and_checks_all_public_boundaries(self):
        result = run_integration_self_test()

        self.assertEqual(result["url_builders_checked"], 8)
        self.assertEqual(result["league_queues_checked"], 5)
        self.assertTrue(result["manual_boundaries"])
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])

    def test_command_route_self_test_covers_natural_integration_phrases(self):
        # The resident self-test must exercise the same parser/catalog path
        # used by voice and mobile text, while remaining completely inert.
        from tools.diagnostics import _check_command_routes

        result = _check_command_routes()

        self.assertGreaterEqual(result["recognized_commands"], 50)
        self.assertFalse(result["external_actions_executed"])

    @patch("tools.integration_diagnostics.build_web_search_url", side_effect=ValueError("invalid"))
    def test_integration_self_test_fails_closed_when_a_builder_breaks(self, _builder):
        with self.assertRaises(ValueError):
            run_integration_self_test()

    @patch(
        "tools.integration_diagnostics.build_integration_capabilities",
        return_value={
            "apple_music": {"playback": True, "requires_manual_selection": True},
            "whatsapp": {"send_message": False, "requires_manual_send": True},
            "discord": {"start_call": False, "requires_manual_call": True},
            "league": {"accept_match": False, "requires_manual_accept": True},
            "codex": {"writes_to_chat": False},
        },
    )
    def test_integration_self_test_rejects_automatic_playback(self, _capabilities):
        with self.assertRaises(ValueError):
            run_integration_self_test()

    def test_secure_audio_self_test_uses_synthetic_pcm_and_bounded_capture(self):
        result = run_secure_audio_self_test()

        self.assertTrue(result["encrypted_round_trip"])
        self.assertTrue(result["capture_gate"])
        self.assertTrue(result["ordered_stream"])
        self.assertTrue(result["bounded_summary"])
        self.assertTrue(result["transcript_bridge"])
        self.assertTrue(result["intent_routed"])
        self.assertEqual(result["voice_intents_checked"], 10)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])

    def test_voice_preview_uses_secure_audio_without_dispatching_tools(self):
        result = preview_secure_audio_transcript("busca una partida en el LoL")

        self.assertEqual(result["transcript"], "busca una partida en el LoL")
        self.assertEqual(result["stream_bytes"], 32)
        self.assertEqual(result["stream_duration_ms"], 1)
        self.assertTrue(result["secure_audio_round_trip"])
        self.assertFalse(result["audio_captured"])
        self.assertTrue(result["hardware_required"])
        self.assertFalse(result["side_effects"])
        self.assertFalse(result["external_actions_executed"])

    def test_voice_preview_rejects_unsafe_transcript_text(self):
        with self.assertRaises(ValueError):
            preview_secure_audio_transcript("texto\u202eoculto")

    def test_secure_self_test_only_reports_successful_bounded_checks(self):
        result = run_secure_self_test()

        self.assertEqual(
            result,
            {
                "handshake": True,
                "encrypted_round_trip": True,
                "tamper_rejected": True,
                "external_actions_executed": False,
                "persistent_keys_touched": False,
            },
        )

    def test_mobile_self_test_covers_all_external_integrations_without_external_actions(self):
        result = run_mobile_protocol_self_test()

        self.assertTrue(result["handshake"])
        self.assertTrue(result["confirmation_gated"])
        self.assertTrue(result["request_binding"])
        self.assertTrue(result["result_redacted"])
        self.assertEqual(result["integration_tools_checked"], 20)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])

    def test_mobile_tcp_self_test_covers_all_external_integrations_on_loopback(self):
        result = run_mobile_tcp_self_test()

        self.assertTrue(result["listener_loopback_only"])
        self.assertTrue(result["network_round_trip"])
        self.assertTrue(result["confirmation_gated"])
        self.assertTrue(result["request_binding"])
        self.assertTrue(result["result_redacted"])
        self.assertEqual(result["integration_tools_checked"], 20)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])


if __name__ == "__main__":
    unittest.main()
