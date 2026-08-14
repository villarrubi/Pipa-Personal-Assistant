import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from tools.integration_protocol_diagnostics import (  # noqa: E402
    run_integration_protocol_self_test,
)


class IntegrationProtocolDiagnosticsTests(unittest.TestCase):
    def test_five_integrations_use_confirmation_and_redacted_device_results(self):
        result = run_integration_protocol_self_test()

        self.assertEqual(result["commands_checked"], 5)
        self.assertTrue(result["confirmation_gated"])
        self.assertTrue(result["executed_only_after_confirmation"])
        self.assertTrue(result["result_redacted"])
        self.assertEqual(result["simulated_handlers_executed"], 5)
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])


if __name__ == "__main__":
    unittest.main()
