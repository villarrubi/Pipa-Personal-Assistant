import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from configure_apps import build_app_payload, main  # noqa: E402


class ConfigureAppsTests(unittest.TestCase):
    def test_build_app_payload_replaces_same_name_and_preserves_others(self):
        result = build_app_payload(
            name="Discord",
            aliases=["discord", "llamadas"],
            launcher="Discord.exe",
            arguments=["--start-minimized"],
            existing={
                "discord": {"aliases": ["viejo"], "command": ["old.exe"]},
                "notepad": {"aliases": ["bloc"], "command": ["notepad.exe"]},
            },
        )

        self.assertNotIn("discord", result)
        self.assertEqual(result["Discord"]["command"], ["Discord.exe", "--start-minimized"])
        self.assertEqual(result["notepad"]["command"], ["notepad.exe"])

    def test_main_validates_without_writing_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            with patch("configure_apps.LOCAL_APPS_FILE", path):
                result = main(
                    [
                        "--name",
                        "Codex",
                        "--alias",
                        "codex",
                        "--launcher",
                        "codex.exe",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertFalse(path.exists())

    def test_main_writes_atomic_validated_payload_only_with_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            with patch("configure_apps.LOCAL_APPS_FILE", path):
                result = main(
                    [
                        "--name",
                        "Discord",
                        "--launcher",
                        "Discord.exe",
                        "--argument=--start-minimized",
                        "--write",
                    ]
                )

                self.assertEqual(result, 0)
                with path.open("r", encoding="utf-8") as file:
                    raw = json.load(file)
                self.assertEqual(raw["Discord"]["command"], ["Discord.exe", "--start-minimized"])
                self.assertEqual(list(path.parent.glob(".apps.*.tmp")), [])

    def test_shell_launcher_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            with patch("configure_apps.LOCAL_APPS_FILE", path):
                result = main(
                    [
                        "--name",
                        "danger",
                        "--launcher",
                        "powershell.exe",
                        "--write",
                    ]
                )

            self.assertEqual(result, 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
