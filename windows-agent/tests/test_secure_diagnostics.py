import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from tools.secure_diagnostics import (  # noqa: E402
    run_mobile_protocol_self_test,
    run_mobile_tcp_self_test,
    run_secure_self_test,
)


class SecureDiagnosticsTests(unittest.TestCase):
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
        self.assertTrue(result["result_redacted"])
        self.assertEqual(result["integration_tools_checked"], 9)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])

    def test_mobile_tcp_self_test_covers_all_external_integrations_on_loopback(self):
        result = run_mobile_tcp_self_test()

        self.assertTrue(result["listener_loopback_only"])
        self.assertTrue(result["network_round_trip"])
        self.assertTrue(result["confirmation_gated"])
        self.assertTrue(result["result_redacted"])
        self.assertEqual(result["integration_tools_checked"], 9)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])


if __name__ == "__main__":
    unittest.main()
