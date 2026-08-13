import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firmware_security_check import (  # noqa: E402
    evaluate_security,
    parse_summary_json,
    read_security_state,
    validate_port,
)


class FirmwareSecurityCheckTests(unittest.TestCase):
    def test_filtered_espefuse_report_keeps_only_security_fields(self):
        output = "banner\n" + json.dumps(
            {
                "SPI_BOOT_CRYPT_CNT": {"value": "Disable", "raw_value": "0x0"},
                "SECURE_BOOT_EN": {"value": False},
                "SECURE_VERSION": {"value": 0},
                "WIFI_MAC": {"value": "private"},
            }
        )

        self.assertEqual(
            parse_summary_json(output),
            {"SPI_BOOT_CRYPT_CNT": "Disable", "SECURE_BOOT_EN": False, "SECURE_VERSION": 0},
        )

    def test_plaintext_development_image_is_allowed_only_on_unsecured_state(self):
        report = evaluate_security(
            {"SPI_BOOT_CRYPT_CNT": "Disable", "SECURE_BOOT_EN": False, "SECURE_VERSION": 0}
        )

        self.assertTrue(report["success"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["failures"], [])

    def test_secure_boot_flash_encryption_and_anti_rollback_fail_closed(self):
        report = evaluate_security(
            {"SPI_BOOT_CRYPT_CNT": "Enable", "SECURE_BOOT_EN": True, "SECURE_VERSION": 2}
        )

        self.assertFalse(report["success"])
        self.assertEqual(
            report["failures"],
            ["secure_boot_enabled", "flash_encryption_enabled", "anti_rollback_version_nonzero"],
        )

    def test_unknown_or_incomplete_values_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_summary_json("{}")
        with self.assertRaises(ValueError):
            evaluate_security({"SPI_BOOT_CRYPT_CNT": "maybe", "SECURE_BOOT_EN": False, "SECURE_VERSION": 0})

    def test_port_validation_is_strict(self):
        self.assertEqual(validate_port(" com7 "), "COM7")
        with self.assertRaises(ValueError):
            validate_port("COM0")
        with self.assertRaises(ValueError):
            validate_port("\\\\.\\COM7")

    @patch("firmware_security_check.subprocess.run")
    def test_device_read_uses_only_the_filtered_read_only_summary(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(
            {
                "SPI_BOOT_CRYPT_CNT": {"value": "Disable"},
                "SECURE_BOOT_EN": {"value": False},
                "SECURE_VERSION": {"value": 0},
            }
        )

        report = read_security_state(
            "COM7",
            python_executable="python.exe",
            espefuse_path="espefuse.py",
        )

        command = run.call_args.args[0]
        self.assertTrue(report["success"])
        self.assertIn("summary", command)
        self.assertIn("--format", command)
        self.assertNotIn("burn", " ".join(command).casefold())
        self.assertEqual(command[-3:], ["SPI_BOOT_CRYPT_CNT", "SECURE_BOOT_EN", "SECURE_VERSION"])


if __name__ == "__main__":
    unittest.main()
