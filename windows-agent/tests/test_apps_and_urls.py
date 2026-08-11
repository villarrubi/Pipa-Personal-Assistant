import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.apps import validate_apps_config  # noqa: E402
from tools.urls import validate_external_url  # noqa: E402


class AppsAndUrlsTests(unittest.TestCase):
    def test_public_app_template_is_loadable(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "apps.example.json"
        )
        with template_path.open("r", encoding="utf-8") as file:
            apps = validate_apps_config(json.load(file))

        self.assertIn("calculator", apps)
        self.assertTrue(apps["calculator"]["command"])

    def test_http_urls_are_allowed(self):
        self.assertEqual(
            validate_external_url("  https://example.com/path  "),
            "https://example.com/path",
        )

    def test_non_http_urls_are_rejected(self):
        for url in ("file:///C:/Windows", "javascript:alert(1)", "ftp://example.com"):
            with self.assertRaises(ValueError):
                validate_external_url(url)

    def test_urls_with_embedded_credentials_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_external_url("https://user:password@example.com/")


if __name__ == "__main__":
    unittest.main()
