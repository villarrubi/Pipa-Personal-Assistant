import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from voice_diagnostics import VoiceDiagnosticStore  # noqa: E402


class VoiceDiagnosticStoreTests(unittest.TestCase):
    def test_records_only_bounded_transcript_and_safe_metadata(self):
        now = [10.0]
        store = VoiceDiagnosticStore(ttl_seconds=30, clock=lambda: now[0])

        store.record(
            "estado del ordenado",
            stt_metadata={
                "model": "base",
                "peak_dbfs": -18.25,
                "language_probability": 0.99,
                "private": "must-not-escape",
            },
            messages=[{"protocol_version": 1, "type": "tool_result", "tool_name": "system_status"}],
        )

        result = store.snapshot()
        self.assertTrue(result["available"])
        self.assertTrue(result["recognized"])
        self.assertEqual(result["transcript"], "estado del ordenado")
        self.assertEqual(result["tool_name"], "system_status")
        self.assertEqual(result["stt"]["model"], "base")
        self.assertNotIn("private", result["stt"])

    def test_tracks_confirmation_and_final_tool_result_for_the_same_capture(self):
        store = VoiceDiagnosticStore(ttl_seconds=30, clock=lambda: 10.0)
        store.record(
            "abre la calculadora",
            stt_metadata=None,
            messages=[
                {
                    "protocol_version": 1,
                    "type": "confirm_request",
                    "tool_name": "open_app",
                }
            ],
        )
        self.assertEqual(store.snapshot()["status"], "confirmation_required")

        store.update_from_messages(
            [
                {
                    "protocol_version": 1,
                    "type": "tool_result",
                    "tool_name": "open_app",
                    "success": True,
                }
            ]
        )

        result = store.snapshot()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["recognized"])

    def test_marks_unknown_command_and_expires_without_persistence(self):
        now = [20.0]
        store = VoiceDiagnosticStore(ttl_seconds=10, clock=lambda: now[0])
        store.record(
            "frase desconocida",
            stt_metadata=None,
            messages=[
                {
                    "protocol_version": 1,
                    "type": "error",
                    "code": "unsupported_text_intent",
                }
            ],
        )

        self.assertEqual(store.snapshot()["status"], "unrecognized")
        now[0] = 31.0
        self.assertEqual(
            store.snapshot(),
            {"success": True, "available": False, "reason": "expired"},
        )


if __name__ == "__main__":
    unittest.main()
