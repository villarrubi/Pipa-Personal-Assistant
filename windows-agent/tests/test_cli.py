import argparse
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipa_cli  # noqa: E402


class CliTests(unittest.TestCase):
    def test_only_loopback_base_urls_are_accepted(self):
        self.assertEqual(pipa_cli._local_base_url("http://127.0.0.1:8765/"), "http://127.0.0.1:8765")
        with self.assertRaises(argparse.ArgumentTypeError):
            pipa_cli._local_base_url("http://192.168.1.50:8765")
        with self.assertRaises(argparse.ArgumentTypeError):
            pipa_cli._local_base_url("http://127.0.0.1:8765/?redirect=remote")
        with self.assertRaises(argparse.ArgumentTypeError):
            pipa_cli._local_base_url("http://localhost:8765")

    def test_help_does_not_require_unicode_console_support(self):
        parser = pipa_cli._parser()
        self.assertIn("Cliente local de pruebas de Pipa.", parser.description)

    def test_local_self_test_is_available_without_the_resident_agent(self):
        arguments = pipa_cli._parser().parse_args(["local-self-test"])
        self.assertEqual(arguments.command, "local-self-test")

    @patch("pipa_cli.get_self_test")
    def test_local_self_test_uses_current_source_and_no_gateway(self, self_test):
        self_test.return_value = {"success": True, "checks": {}}

        result = pipa_cli.main(["local-self-test"])

        self.assertEqual(result, 0)
        self_test.assert_called_once_with(
            serial_gateway_configured=False,
            serial_gateway_running=False,
            serial_gateway_connected=False,
            mobile_gateway_configured=False,
            mobile_gateway_running=False,
            mobile_gateway_connected=False,
        )

    def test_output_encoding_configuration_is_safe_for_fixed_test_streams(self):
        pipa_cli._configure_output_encoding()

    @patch("pipa_cli.urlopen")
    def test_mutating_commands_include_local_header(self, open_url):
        response = MagicMock()
        response.read.return_value = json.dumps({"success": True}).encode()
        response.__enter__.return_value = response
        open_url.return_value = response

        result = pipa_cli._request("http://127.0.0.1:8765", "POST", "/music/open", {})

        self.assertTrue(result["success"])
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("X-pipa-local-request"), "1")
        self.assertEqual(request.get_header("X-pipa-local-confirmation"), "1")

    @patch("pipa_cli.urlopen")
    def test_delete_commands_include_local_header_without_a_body(self, open_url):
        response = MagicMock()
        response.read.return_value = json.dumps({"success": True}).encode()
        response.__enter__.return_value = response
        open_url.return_value = response

        pipa_cli._request("http://127.0.0.1:8765", "DELETE", "/league/search")

        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("X-pipa-local-request"), "1")
        self.assertEqual(request.get_header("X-pipa-local-confirmation"), "1")

    @patch("pipa_cli.urlopen")
    def test_http_errors_do_not_echo_agent_response_body(self, open_url):
        error = HTTPError(
            "http://127.0.0.1:8765/open-url",
            400,
            "bad request",
            {"Content-Type": "application/json"},
            MagicMock(read=lambda _size: b'{"detail":"private-url-and-token"}'),
        )
        open_url.side_effect = error

        with self.assertRaisesRegex(RuntimeError, r"El agente rechazó la solicitud \(HTTP 400\)\.") as raised:
            pipa_cli._request("http://127.0.0.1:8765", "POST", "/open-url", {"url": "https://example.com"})

        self.assertNotIn("private-url-and-token", str(raised.exception))

    def test_routes_are_bounded_to_expected_agent_paths(self):
        arguments = pipa_cli._parser().parse_args(["capabilities"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/capabilities", None))

        arguments = pipa_cli._parser().parse_args(["integration-status"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/integrations/status", None))

        arguments = pipa_cli._parser().parse_args(["commands"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/commands", None))

        arguments = pipa_cli._parser().parse_args(["self-test"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/self-test", None))

        arguments = pipa_cli._parser().parse_args(["league-search", "solo"])
        self.assertEqual(pipa_cli._route(arguments), ("POST", "/league/search", {"queue": "solo"}))

        arguments = pipa_cli._parser().parse_args(["league-search-status"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/league/search/status", None))

        arguments = pipa_cli._parser().parse_args(["open-app", "codex"])
        self.assertEqual(pipa_cli._route(arguments), ("POST", "/open-app", {"app": "codex"}))

        arguments = pipa_cli._parser().parse_args(["lock"])
        self.assertEqual(pipa_cli._route(arguments), ("POST", "/system/lock", {}))

        arguments = pipa_cli._parser().parse_args(["open-url", "https://example.com"])
        self.assertEqual(
            pipa_cli._route(arguments),
            ("POST", "/open-url", {"url": "https://example.com"}),
        )

        arguments = pipa_cli._parser().parse_args(["audio-volume"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/audio/volume", None))

        arguments = pipa_cli._parser().parse_args(["audio-volume", "40"])
        self.assertEqual(pipa_cli._route(arguments), ("POST", "/audio/volume", {"percent": 40}))

        arguments = pipa_cli._parser().parse_args(["power-status"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/system/power", None))

        arguments = pipa_cli._parser().parse_args(["network-status"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/system/network", None))

        arguments = pipa_cli._parser().parse_args(["timer-create", "30", "break"])
        self.assertEqual(
            pipa_cli._route(arguments),
            ("POST", "/timers", {"seconds": 30, "label": "break"}),
        )

        arguments = pipa_cli._parser().parse_args(["timer-cancel", "abc_123"])
        self.assertEqual(pipa_cli._route(arguments), ("DELETE", "/timers/abc_123", None))
        invalid = pipa_cli._parser().parse_args(["timer-cancel", "../status"])
        with self.assertRaises(RuntimeError):
            pipa_cli._route(invalid)

    @patch("pipa_cli.run_secure_self_test")
    def test_secure_test_is_local_and_reports_bounded_checks(self, secure_test):
        secure_test.return_value = {
            "handshake": True,
            "encrypted_round_trip": True,
            "tamper_rejected": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["secure-test"])

        self.assertEqual(result, 0)
        secure_test.assert_called_once_with()

    @patch("pipa_cli.run_mobile_protocol_self_test")
    def test_mobile_test_is_in_memory_and_reports_bounded_checks(self, mobile_test):
        mobile_test.return_value = {
            "handshake": True,
            "capabilities_acknowledged": True,
            "confirmation_gated": True,
            "result_redacted": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["mobile-test"])

        self.assertEqual(result, 0)
        mobile_test.assert_called_once_with()

    @patch("pipa_cli.run_mobile_tcp_self_test")
    def test_mobile_tcp_test_reports_loopback_checks(self, tcp_test):
        tcp_test.return_value = {
            "listener_loopback_only": True,
            "network_round_trip": True,
            "confirmation_gated": True,
            "result_redacted": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["mobile-tcp-test"])

        self.assertEqual(result, 0)
        tcp_test.assert_called_once_with()

    @patch(
        "pipa_cli._request",
        side_effect=[
            {"success": True, "pc": "online"},
            {"success": True, "integrations": {}},
            {"success": True, "commands": []},
            {"success": True, "protocol_version": 1, "tool_names": []},
            {"success": True, "checks": {}},
        ],
    )
    def test_doctor_is_read_only_and_checks_all_local_surfaces(self, request):
        result = pipa_cli._doctor("http://127.0.0.1:8765")

        self.assertTrue(result["success"])
        self.assertTrue(all(check["ok"] for check in result["checks"].values()))
        self.assertEqual(request.call_count, 5)
        self.assertTrue(all(call.args[1] == "GET" for call in request.call_args_list))

    @patch(
        "pipa_cli._request",
        side_effect=[
            {"success": True, "pc": "online"},
            {"success": True},
            {"success": True},
            {"success": True, "protocol_version": 1, "tool_names": []},
            {"success": True},
        ],
    )
    def test_doctor_rejects_an_incomplete_response_shape(self, request):
        result = pipa_cli._doctor("http://127.0.0.1:8765")

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["capabilities"]["ok"])
        self.assertFalse(result["checks"]["self_test"]["ok"])
        self.assertEqual(request.call_count, 5)

    def test_external_commands_require_explicit_cli_confirmation(self):
        arguments = pipa_cli._parser().parse_args(["music-search", "Daft Punk"])
        self.assertFalse(arguments.confirm)
        confirmed = pipa_cli._parser().parse_args(["music-search", "Daft Punk", "--confirm"])
        self.assertTrue(confirmed.confirm)
        open_url = pipa_cli._parser().parse_args(["open-url", "https://example.com"])
        self.assertFalse(open_url.confirm)
        whatsapp_contact = pipa_cli._parser().parse_args(["whatsapp-contact", "mama", "Hola"])
        self.assertFalse(whatsapp_contact.confirm)
        whatsapp_contact_open = pipa_cli._parser().parse_args(["whatsapp-contact-open", "mama"])
        self.assertFalse(whatsapp_contact_open.confirm)
        discord_contact = pipa_cli._parser().parse_args(["discord-contact", "mama", "--confirm"])
        self.assertTrue(discord_contact.confirm)
        discord_call = pipa_cli._parser().parse_args(["discord-call", "mama", "--confirm"])
        self.assertTrue(discord_call.confirm)

    @patch("pipa_cli._request")
    def test_main_does_not_execute_external_command_without_confirmation(self, request):
        result = pipa_cli.main(["league-search", "solo"])

        self.assertEqual(result, 1)
        request.assert_not_called()

    def test_intent_inspection_has_no_side_effects(self):
        result = pipa_cli._inspect_intent("prepara WhatsApp para +34 600 123 456 y dile Hola")

        self.assertTrue(result["recognized"])
        self.assertEqual(result["tool_name"], "whatsapp_compose")
        self.assertFalse(result["side_effects"])

    def test_intent_preview_exposes_confirmation_without_executing(self):
        result = pipa_cli._preview_intent("busca una partida clasificatoria solo")

        self.assertTrue(result["recognized"])
        self.assertEqual(result["tool_name"], "league_search")
        self.assertTrue(result["requires_confirmation"])
        self.assertFalse(result["side_effects"])
        self.assertEqual(result["message"], "Buscar partida: ranked_solo")

    def test_intent_preview_marks_safe_commands(self):
        result = pipa_cli._preview_intent("estado de matchmaking")

        self.assertEqual(result["tool_name"], "league_status")
        self.assertFalse(result["requires_confirmation"])


if __name__ == "__main__":
    unittest.main()
