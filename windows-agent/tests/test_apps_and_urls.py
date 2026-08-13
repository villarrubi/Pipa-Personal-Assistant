import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.system as system  # noqa: E402
from tools.apps import MAX_CONFIG_FILE_BYTES, load_apps, open_app, validate_apps_config  # noqa: E402
from tools.browser import without_destination  # noqa: E402
from tools.commands import (  # noqa: E402
    build_apple_music_search_url,
    build_web_search_url,
)
from tools.league import (  # noqa: E402
    LeagueClientError,
    find_client_connection,
    parse_client_command_line,
    resolve_queue_id,
)
from tools.urls import validate_external_url  # noqa: E402
from tools.whatsapp import build_whatsapp_chat_url, build_whatsapp_compose_url, normalize_phone  # noqa: E402


class AppsAndUrlsTests(unittest.TestCase):
    def test_browser_destination_is_removed_from_public_result(self):
        result = without_destination({"success": True, "url": "https://example.com", "sent": False})

        self.assertEqual(result, {"success": True, "sent": False})

    def test_public_app_template_is_loadable(self):
        template_path = Path(__file__).resolve().parents[1] / "config" / "apps.example.json"
        with template_path.open("r", encoding="utf-8") as file:
            apps = validate_apps_config(json.load(file))

        self.assertIn("calculator", apps)
        self.assertTrue(apps["calculator"]["command"])
        self.assertTrue(
            all(argument.lower() != "cmd" for data in apps.values() for argument in data["command"])
        )

    def test_app_config_rejects_control_characters_and_unbounded_commands(self):
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo\x00"], "command": ["demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo"], "command": ["x" * 1025]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo\u202e": {"aliases": ["demo"], "command": ["demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["de\u2066mo"], "command": ["demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo"], "command": ["cmd.exe", "/c", "demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo"], "command": ["demo.exe", "/c"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo", "demo"], "command": ["demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({" demo": {"aliases": ["demo"], "command": ["demo.exe"]}})
        with self.assertRaises(ValueError):
            validate_apps_config({"demo": {"aliases": ["demo"], "command": [""]}})

    def test_app_config_rejects_ambiguous_aliases_and_too_many_apps(self):
        with self.assertRaises(ValueError):
            validate_apps_config(
                {
                    "first": {"aliases": ["shared"], "command": ["first.exe"]},
                    "second": {"aliases": ["shared"], "command": ["second.exe"]},
                }
            )
        too_many = {
            f"app-{index}": {"aliases": [f"alias-{index}"], "command": ["app.exe"]} for index in range(65)
        }
        with self.assertRaises(ValueError):
            validate_apps_config(too_many)

    def test_app_file_size_is_bounded_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            path.write_text("{" + " " * MAX_CONFIG_FILE_BYTES + "}", encoding="utf-8")
            with patch("tools.apps.LOCAL_APPS_FILE", path):
                with self.assertRaises(ValueError):
                    load_apps()

    def test_app_file_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            path.write_bytes(b"\xff")
            with patch("tools.apps.LOCAL_APPS_FILE", path):
                with self.assertRaises(ValueError):
                    load_apps()

    @patch("tools.apps.subprocess.Popen")
    @patch("tools.apps.load_apps")
    def test_windows_app_launch_suppresses_console_window(self, load_apps, popen):
        load_apps.return_value = {"demo": {"aliases": ["demo"], "command": ["demo.exe"]}}

        result = open_app("demo")

        self.assertTrue(result["success"])
        if sys.platform == "win32":
            self.assertIn("creationflags", popen.call_args.kwargs)

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

    def test_urls_with_controls_or_invalid_ports_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_external_url("https://example.com/search\nnext")
        with self.assertRaises(ValueError):
            validate_external_url("https://example.com:99999/")

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

    def test_search_queries_reject_invisible_controls(self):
        for builder in (build_web_search_url, build_apple_music_search_url):
            with self.subTest(builder=builder.__name__):
                with self.assertRaises(ValueError):
                    builder("Pipa\u202ecodex")

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

    def test_league_client_arguments_require_exact_unique_flags(self):
        with self.assertRaises(LeagueClientError):
            parse_client_command_line(
                ["LeagueClientUx.exe", "prefix--app-port=54321", "--remoting-auth-token=secret-token"]
            )
        with self.assertRaises(LeagueClientError):
            parse_client_command_line(
                [
                    "LeagueClientUx.exe",
                    "--app-port=54321",
                    "--app-port=54322",
                    "--remoting-auth-token=secret-token",
                ]
            )
        with self.assertRaises(LeagueClientError):
            parse_client_command_line(
                ["LeagueClientUx.exe", "--app-port=54321", "--remoting-auth-token=secret token"]
            )

    @patch("tools.league.getpass.getuser", return_value="DESKTOP\\User")
    @patch("tools.league.psutil.process_iter")
    def test_league_discovery_ignores_a_client_owned_by_another_user(self, process_iter, _getuser):
        process_iter.return_value = [
            SimpleNamespace(
                info={
                    "name": "LeagueClientUx.exe",
                    "username": "DESKTOP\\Other",
                    "cmdline": [
                        "LeagueClientUx.exe",
                        "--app-port=54321",
                        "--remoting-auth-token=other-token",
                    ],
                }
            ),
            SimpleNamespace(
                info={
                    "name": "LeagueClientUx.exe",
                    "username": "DESKTOP\\User",
                    "cmdline": [
                        "LeagueClientUx.exe",
                        "--app-port=54322",
                        "--remoting-auth-token=current-token",
                    ],
                }
            ),
        ]

        connection = find_client_connection()

        self.assertEqual(connection.port, 54322)
        self.assertEqual(connection.token, "current-token")

    @patch("tools.league.psutil.process_iter")
    def test_league_discovery_fails_closed_when_process_owner_is_unavailable(self, process_iter):
        process_iter.return_value = [
            SimpleNamespace(
                info={
                    "name": "LeagueClientUx.exe",
                    "username": None,
                    "cmdline": [
                        "LeagueClientUx.exe",
                        "--app-port=54321",
                        "--remoting-auth-token=unknown-owner-token",
                    ],
                }
            )
        ]

        with self.assertRaises(LeagueClientError):
            find_client_connection()

    def test_whatsapp_compose_url_normalizes_phone_and_encodes_message(self):
        self.assertEqual(normalize_phone("+34 600-123-456"), "34600123456")
        url = build_whatsapp_compose_url("+34 600-123-456", "Hola, Pipα")

        self.assertTrue(url.startswith("https://wa.me/34600123456?text="))
        self.assertIn("Pip%CE%B1", url)

    def test_whatsapp_chat_url_contains_no_message_payload(self):
        self.assertEqual(build_whatsapp_chat_url("+34 600-123-456"), "https://wa.me/34600123456")

    def test_whatsapp_rejects_invalid_phone(self):
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("not-a-phone", "Hola")
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("000000000000000", "Hola")
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("01234567", "Hola")
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("+34\u00a0600123456", "Hola")

    def test_whatsapp_message_rejects_invisible_controls_but_allows_line_feed(self):
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("+34 600-123-456", "Hola\x00Mamá")
        with self.assertRaises(ValueError):
            build_whatsapp_compose_url("+34 600-123-456", "Hola\u202eMamá")

        url = build_whatsapp_compose_url("+34 600-123-456", "Hola\nMamá")
        self.assertTrue(url.startswith("https://wa.me/34600123456?text="))

    @patch.object(system, "ctypes")
    def test_lock_failure_does_not_return_platform_exception(self, ctypes):
        ctypes.windll.user32.LockWorkStation.side_effect = OSError("private detail")
        result = system.lock_pc()

        self.assertFalse(result["success"])
        self.assertNotIn("error", result)
        self.assertNotIn("private detail", str(result))
        ctypes.windll.user32.LockWorkStation.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
