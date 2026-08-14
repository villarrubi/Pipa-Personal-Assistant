import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from tools.integration_protocol_diagnostics import (  # noqa: E402
    INTEGRATION_CASE_COUNT,
    VOICE_INTEGRATION_CASE_COUNT,
    run_integration_protocol_self_test,
)


class IntegrationProtocolDiagnosticsTests(unittest.TestCase):
    def test_all_external_integration_tools_use_confirmation_and_redacted_results(self):
        result = run_integration_protocol_self_test()

        self.assertEqual(result["commands_checked"], INTEGRATION_CASE_COUNT)
        self.assertEqual(result["voice_commands_checked"], VOICE_INTEGRATION_CASE_COUNT)
        self.assertTrue(result["confirmation_gated"])
        self.assertTrue(result["executed_only_after_confirmation"])
        self.assertTrue(result["result_redacted"])
        self.assertEqual(
            result["simulated_handlers_executed"],
            INTEGRATION_CASE_COUNT + VOICE_INTEGRATION_CASE_COUNT,
        )
        self.assertFalse(result["external_actions_executed"])
        self.assertFalse(result["persistent_keys_touched"])


if __name__ == "__main__":
    unittest.main()
