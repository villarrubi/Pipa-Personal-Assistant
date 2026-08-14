import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.app_diagnostics import inspect_apps  # noqa: E402
from tools.apps import AppsConfigError  # noqa: E402


class AppDiagnosticsTests(unittest.TestCase):
    @patch(
        "tools.app_diagnostics.shutil.which",
        side_effect=lambda value: value if value == "codex.exe" else None,
    )
    @patch("tools.app_diagnostics.load_apps")
    def test_reports_readiness_without_exposing_commands(self, load_apps, _which):
        load_apps.return_value = {
            "codex": {"aliases": ["Codex"], "command": ["codex.exe"]},
            "league": {"aliases": ["lol"], "command": ["LeagueClient.exe"]},
        }

        result = inspect_apps()

        self.assertTrue(result["success"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["configured_count"], 2)
        self.assertEqual(result["unresolved_count"], 1)
        self.assertTrue(result["apps"]["codex"]["launcher_resolved"])
        self.assertFalse(result["apps"]["league"]["launcher_resolved"])
        self.assertNotIn("command", str(result))
        self.assertNotIn("codex.exe", str(result))

    @patch("tools.app_diagnostics.load_apps", side_effect=AppsConfigError("private path"))
    def test_invalid_config_fails_closed_without_echoing_details(self, _load_apps):
        result = inspect_apps()

        self.assertFalse(result["success"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["error"], "apps_config_invalid")
        self.assertNotIn("private path", str(result))


if __name__ == "__main__":
    unittest.main()
