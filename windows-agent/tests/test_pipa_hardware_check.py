import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from pipa_hardware_check import HardwareDiagnostics, _port  # noqa: E402


class HardwareDiagnosticsTests(unittest.TestCase):
    def test_v2_boot_markers_produce_a_safe_success_report(self):
        diagnostics = HardwareDiagnostics()
        for line in (
            b"# Pipa firmware 0.2.0 starting\n",
            b"# board revision: 2\n",
            b"# PIPA_PUBLIC_KEY=secret-public-key-must-not-be-returned\n",
            b"# IO expander ready\n",
            b"# display ready\n",
            b"# battery ADC ready\n",
            b"# touch controller ready\n",
            b"# audio codec probe ready\n",
            b"# audio output ES8311: present\n",
            b"# audio input ES7210: absent\n",
        ):
            diagnostics.observe(line)

        result = diagnostics.result(2)

        self.assertTrue(result["success"])
        self.assertTrue(result["public_key_seen"])
        self.assertNotIn("secret-public-key", str(result))
        self.assertEqual(
            result["audio"],
            {"probe_ready": True, "output_codec_present": True, "input_codec_present": False},
        )
        self.assertEqual(result["failures"], [])

    def test_audio_markers_are_optional_and_absent_values_are_bounded(self):
        diagnostics = HardwareDiagnostics()
        for line in (
            "# board revision: 2",
            "# PIPA_PUBLIC_KEY=hidden",
            "# IO expander ready",
            "# display ready",
            "# battery ADC ready",
            "# touch controller ready",
            "# audio codecs not detected",
            "# audio output ES8311: absent",
            "# audio input ES7210: absent",
        ):
            diagnostics.observe(line)

        result = diagnostics.result(2)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["audio"],
            {"probe_ready": False, "output_codec_present": False, "input_codec_present": False},
        )
        self.assertNotIn("hidden", str(result))

    def test_invalid_json_and_non_diagnostic_lines_are_not_echoed(self):
        diagnostics = HardwareDiagnostics()
        diagnostics.observe(b'{"type":"hello","signature":"secret"}\n')
        diagnostics.observe(b"# Wi-Fi ready: 192.168.1.50\n")

        result = diagnostics.result(2)

        self.assertEqual(result["lines_seen"], 1)
        self.assertFalse(result["public_key_seen"])
        self.assertNotIn("192.168.1.50", str(result))
        self.assertNotIn("secret", str(result))

    def test_unexpected_revision_and_fatal_boot_fail_closed(self):
        diagnostics = HardwareDiagnostics()
        diagnostics.observe("# board revision: 1")
        diagnostics.observe("# FATAL: identity unavailable")

        result = diagnostics.result(2)

        self.assertFalse(result["success"])
        self.assertIn("unexpected_board_revision", result["failures"])
        self.assertIn("fatal_boot_error", result["failures"])

    def test_port_validation_is_explicit(self):
        with patch("pipa_hardware_check.platform.system", return_value="Windows"):
            self.assertEqual(_port(" com7 "), "COM7")
            with self.assertRaises(argparse.ArgumentTypeError):
                _port("COM1000")


if __name__ == "__main__":
    unittest.main()
