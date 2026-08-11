import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.discord import build_discord_channel_url, open_discord_channel  # noqa: E402


class DiscordTests(unittest.TestCase):
    def test_builds_dm_url(self):
        self.assertEqual(
            build_discord_channel_url("12345678901234567"),
            "https://discord.com/channels/@me/12345678901234567",
        )

    def test_builds_server_channel_url(self):
        url = build_discord_channel_url("12345678901234567", "98765432109876543")
        self.assertEqual(url, "https://discord.com/channels/98765432109876543/12345678901234567")

    def test_rejects_invalid_ids(self):
        with self.assertRaises(ValueError):
            build_discord_channel_url("not-an-id")

    @patch("tools.discord.webbrowser.open", return_value=True)
    def test_open_only_prepares_channel(self, open_browser):
        result = open_discord_channel("12345678901234567")
        self.assertFalse(result["call_started"])
        open_browser.assert_called_once()


if __name__ == "__main__":
    unittest.main()
