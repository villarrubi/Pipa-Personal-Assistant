import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.apps import validate_apps_config  # noqa: E402
from tools.commands import (  # noqa: E402
    build_apple_music_search_url,
    build_web_search_url,
)
from tools.league import parse_client_command_line, resolve_queue_id  # noqa: E402
from tools.urls import validate_external_url  # noqa: E402
from tools.whatsapp import build_whatsapp_compose_url, normalize_phone  # noqa: E402


class AppsAndUrlsTests(unittest.TestCase):
    def test_public_app_template_is_loadable(self):
        template_path = Path(__file__).resolve().parents[1] / "config" / "apps.example.json"
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

    def test_web_search_url_is_bounded_and_encoded(self):
        url = build_web_search_url("qué buscar")

        self.assertTrue(url.startswith("https://www.google.com/search?q="))
        self.assertIn("%C3%A9", url)

    def test_apple_music_search_url_is_bounded_and_encoded(self):
        url = build_apple_music_search_url("artista canción")

        self.assertTrue(url.startswith("https://music.apple.com/es/search?term="))
        self.assertIn("%C3%B3", url)

    def test_search_queries_cannot_be_unbounded(self):
        with self.assertRaises(ValueError):
            build_web_search_url("x" * 201)

    def test_league_queue_allowlist(self):
        self.assertEqual(resolve_queue_id("ranked_solo"), 420)
        with self.assertRaises(ValueError):
            resolve_queue_id("custom-dangerous-queue")

    def test_league_client_arguments_are_parsed_without_exposing_token(self):
        connection = parse_client_command_line(
            [
                "LeagueClientUx.exe",
                "--app-port=54321",
                "--remoting-auth-token=secret-token",
            ]
        )

        self.assertEqual(connection.port, 54321)
        self.assertEqual(connection.token, "secret-token")

    def test_whatsapp_compose_url_normalizes_phone_and_encodes_message(self):
        self.assertEqual(normalize_phone("+34 600-123-456"), "34600123456")
        url = build_whatsapp_compose_url("+34 600-123-456", "Hola, Pipα")

        self.assertTrue(url.startswith("https://wa.me/34600123456?text="))
        self.assertIn("Pip%CE%B1", url)

    def test_whatsapp_rejects_invalid_phone(self):
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("not-a-phone", "Hola")


if __name__ == "__main__":
    unittest.main()
