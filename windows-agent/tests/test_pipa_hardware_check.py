import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from pipa_hardware_check import HardwareDiagnostics, _collect_fixture, _port, main  # noqa: E402


class HardwareDiagnosticsTests(unittest.TestCase):
    def test_v2_boot_markers_produce_a_safe_success_report(self):
        diagnostics = HardwareDiagnostics()
        public_key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        for line in (
            b"# Pipa firmware 0.2.0 starting\n",
            b"# board revision: 2\n",
            f"# PIPA_PUBLIC_KEY={public_key}\n".encode(),
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
        self.assertTrue(result["public_key_valid"])
        self.assertNotIn(public_key, str(result))
        self.assertEqual(
            result["audio"],
            {"probe_ready": True, "output_codec_present": True, "input_codec_present": False},
        )
        self.assertEqual(result["failures"], [])

    def test_audio_markers_are_optional_and_absent_values_are_bounded(self):
        diagnostics = HardwareDiagnostics()
        for line in (
            "# board revision: 2",
            "# PIPA_PUBLIC_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
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
        self.assertNotIn("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", str(result))

    def test_public_key_fingerprint_is_opt_in_and_contains_no_key(self):
        diagnostics = HardwareDiagnostics()
        public_key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        diagnostics.observe(f"# PIPA_PUBLIC_KEY={public_key}")

        result = diagnostics.result(2, include_fingerprint=True)

        self.assertTrue(result["public_key_valid"])
        self.assertEqual(
            result["public_key_fingerprint"],
            "63:0D:CD:29:66:C4:33:66:91:12:54:48:BB:B2:5B:4F:F4:12:A4:9C:73:2D:B2:C8:AB:C1:B8:58:1B:D7:10:DD",
        )
        self.assertNotIn(public_key, str(result))

    def test_invalid_public_key_marker_fails_closed(self):
        diagnostics = HardwareDiagnostics()
        diagnostics.observe("# PIPA_PUBLIC_KEY=not-a-public-key")

        result = diagnostics.result(2)

        self.assertTrue(result["public_key_seen"])
        self.assertFalse(result["public_key_valid"])
        self.assertIn("public_key_marker_invalid", result["failures"])

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

    def test_fixture_uses_the_same_parser_without_opening_serial(self):
        fixture = "\n".join(
            (
                "# board revision: 2",
                "# PIPA_PUBLIC_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
                "# IO expander ready",
                "# display ready",
                "# battery ADC ready",
                "# touch controller ready",
                "# audio codecs not detected",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "waveshare-v2.txt"
            path.write_text(fixture, encoding="utf-8")
            with patch("pipa_hardware_check._collect", side_effect=AssertionError("serial opened")):
                diagnostics = _collect_fixture(str(path))
            report = diagnostics.result(2)

        self.assertTrue(report["success"])
        self.assertFalse(report["audio"]["probe_ready"])

    def test_fixture_cli_returns_redacted_json(self):
        fixture = "\n".join(
            (
                "# board revision: 2",
                "# PIPA_PUBLIC_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
                "# IO expander ready",
                "# display ready",
                "# battery ADC ready",
                "# touch controller ready",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "waveshare-v2.txt"
            path.write_text(fixture, encoding="utf-8")
            with patch("sys.stdout") as stdout:
                self.assertEqual(main(["--fixture", str(path), "--json", "--fingerprint"]), 0)
                output = "".join(call.args[0] for call in stdout.write.call_args_list)

        report = json.loads(output)
        self.assertTrue(report["success"])
        self.assertIn("public_key_fingerprint", report)
        self.assertNotIn("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", output)


if __name__ == "__main__":
    unittest.main()
