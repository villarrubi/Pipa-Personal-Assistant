import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.commands import open_league  # noqa: E402
from tools.league import LeagueClientError  # noqa: E402


class LeagueLaunchTests(unittest.TestCase):
    @patch("tools.commands.wait_for_client_connection", side_effect=LeagueClientError("not ready"))
    @patch("tools.commands.open_app", return_value={"success": True, "app": "league_of_legends"})
    def test_open_league_does_not_claim_ready_when_riot_only_opens(self, _open_app, _wait_for_client):
        result = open_league()

        self.assertFalse(result["success"])
        self.assertIn("no ha llegado a iniciar", result["message"])

    @patch("tools.commands.wait_for_client_connection", return_value=object())
    @patch("tools.commands.open_app", return_value={"success": True, "app": "league_of_legends"})
    def test_open_league_reports_ready_client(self, _open_app, _wait_for_client):
        result = open_league()

        self.assertTrue(result["success"])
        self.assertTrue(result["client_ready"])


if __name__ == "__main__":
    unittest.main()
