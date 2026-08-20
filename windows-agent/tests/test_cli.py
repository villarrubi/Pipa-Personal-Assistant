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

    def test_local_capabilities_is_available_without_the_resident_agent(self):
        arguments = pipa_cli._parser().parse_args(["local-capabilities"])
        self.assertEqual(arguments.command, "local-capabilities")

    def test_voice_preview_is_available_without_hardware(self):
        arguments = pipa_cli._parser().parse_args(["voice-preview", "busca", "una", "partida"])
        self.assertEqual(arguments.command, "voice-preview")

    def test_voice_preview_routes_through_secure_audio_and_never_executes(self):
        with patch(
            "pipa_cli.preview_secure_audio_transcript",
            return_value={
                "transcript": "busca una partida",
                "stream_bytes": 32,
                "stream_duration_ms": 1,
                "secure_audio_round_trip": True,
                "audio_captured": False,
                "hardware_required": True,
            },
        ) as preview_audio:
            result = pipa_cli.main(["voice-preview", "busca", "una", "partida"])

        self.assertEqual(result, 0)
        preview_audio.assert_called_once_with("busca una partida")

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

    @patch("pipa_cli.get_capabilities")
    def test_local_capabilities_uses_current_source_and_no_gateway(self, capabilities):
        capabilities.return_value = {"success": True, "integrations": {}}

        result = pipa_cli.main(["local-capabilities"])

        self.assertEqual(result, 0)
        capabilities.assert_called_once_with(
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
    def test_request_passes_custom_timeout(self, open_url):
        response = MagicMock()
        response.read.return_value = json.dumps({"success": True}).encode()
        response.__enter__.return_value = response
        open_url.return_value = response

        pipa_cli._request(
            "http://127.0.0.1:8765",
            "POST",
            "/league/open",
            {},
            timeout=40,
        )

        self.assertEqual(open_url.call_args.kwargs["timeout"], 40)

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

        arguments = pipa_cli._parser().parse_args(["readiness"])
        self.assertEqual(arguments.command, "readiness")

        arguments = pipa_cli._parser().parse_args(["commands"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/commands", None))

        arguments = pipa_cli._parser().parse_args(["self-test"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/self-test", None))

        arguments = pipa_cli._parser().parse_args(["voice-last"])
        self.assertEqual(pipa_cli._route(arguments), ("GET", "/voice/diagnostics", None))

        arguments = pipa_cli._parser().parse_args(["league-search", "solo"])
        self.assertEqual(pipa_cli._route(arguments), ("POST", "/league/search", {"queue": "solo"}))

        arguments = pipa_cli._parser().parse_args(["league-wait", "45"])
        self.assertEqual(
            pipa_cli._route(arguments),
            ("POST", "/league/search/wait", {"seconds": 45}),
        )
        self.assertEqual(pipa_cli._request_timeout(arguments), 50)

        arguments = pipa_cli._parser().parse_args(["league-open"])
        self.assertEqual(pipa_cli._request_timeout(arguments), 40)

        expected_music_actions = {
            "music-play": "play_pause",
            "music-next": "next",
            "music-previous": "previous",
            "music-stop": "stop",
        }
        for command, action in expected_music_actions.items():
            with self.subTest(command=command):
                arguments = pipa_cli._parser().parse_args([command])
                self.assertEqual(
                    pipa_cli._route(arguments),
                    ("POST", "/media/action", {"action": action}),
                )

        arguments = pipa_cli._parser().parse_args(["whatsapp-phone-open", "+34600123456"])
        self.assertEqual(
            pipa_cli._route(arguments),
            ("POST", "/whatsapp/phone/open", {"phone": "+34600123456"}),
        )

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

    @patch("pipa_cli.run_device_protocol_self_test")
    def test_device_test_is_local_and_does_not_require_hardware(self, device_test):
        device_test.return_value = {
            "authenticated": True,
            "safe_text_command": True,
            "confirmation_gated": True,
            "missing_touch_rejected": True,
            "result_redacted": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["device-test"])

        self.assertEqual(result, 0)
        device_test.assert_called_once_with()

    @patch("pipa_cli.run_secure_audio_self_test")
    def test_secure_audio_test_is_local_and_does_not_require_hardware(self, audio_test):
        audio_test.return_value = {
            "encrypted_round_trip": True,
            "capture_gate": True,
            "ordered_stream": True,
            "bounded_summary": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["secure-audio-test"])

        self.assertEqual(result, 0)
        audio_test.assert_called_once_with()

    @patch("pipa_cli.run_integration_self_test")
    def test_integration_test_is_local_and_does_not_require_hardware(self, integration_test):
        integration_test.return_value = {
            "url_builders_checked": 8,
            "league_queues_checked": 5,
            "manual_boundaries": True,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["integration-test"])

        self.assertEqual(result, 0)
        integration_test.assert_called_once_with()

    @patch("pipa_cli.run_integration_protocol_self_test")
    def test_integration_protocol_test_is_local_and_does_not_require_hardware(self, protocol_test):
        protocol_test.return_value = {
            "commands_checked": 18,
            "read_only_commands_checked": 3,
            "confirmation_gated": True,
            "executed_only_after_confirmation": True,
            "result_redacted": True,
            "simulated_handlers_executed": 26,
            "external_actions_executed": False,
            "persistent_keys_touched": False,
        }

        result = pipa_cli.main(["integration-protocol-test"])

        self.assertEqual(result, 0)
        protocol_test.assert_called_once_with()

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

    def _doctor_capability_fixture(self):
        integrations = {
            group: {field: False for field in fields}
            for group, fields in pipa_cli._INTEGRATION_ALIGNMENT_FIELDS.items()
        }
        return {"success": True, "integrations": integrations, "commands": []}

    @patch("pipa_cli._local_capabilities")
    @patch("pipa_cli._request")
    def test_doctor_is_read_only_and_checks_all_local_surfaces(self, request, local_capabilities):
        capabilities = self._doctor_capability_fixture()
        local_capabilities.return_value = capabilities
        request.side_effect = [
            {"success": True, "pc": "online"},
            capabilities,
            {"success": True, "apps": {}, "contacts": {}, "integrations": {}},
            {"success": True, "commands": []},
            {"success": True, "protocol_version": 1, "tool_names": []},
            {"success": True, "checks": {}},
        ]

        result = pipa_cli._doctor("http://127.0.0.1:8765")

        self.assertTrue(result["success"])
        self.assertTrue(all(check["ok"] for check in result["checks"].values()))
        self.assertTrue(result["checks"]["source_alignment"]["ok"])
        self.assertEqual(request.call_count, 6)
        self.assertTrue(all(call.args[1] == "GET" for call in request.call_args_list))

    @patch("pipa_cli._local_capabilities")
    @patch("pipa_cli._request")
    def test_doctor_rejects_an_incomplete_response_shape(self, request, local_capabilities):
        local_capabilities.return_value = self._doctor_capability_fixture()
        request.side_effect = [
            {"success": True, "pc": "online"},
            {"success": True},
            {"success": True},
            {"success": True},
            {"success": True, "protocol_version": 1, "tool_names": []},
            {"success": True},
        ]

        result = pipa_cli._doctor("http://127.0.0.1:8765")

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["capabilities"]["ok"])
        self.assertFalse(result["checks"]["self_test"]["ok"])
        self.assertEqual(request.call_count, 6)

    @patch("pipa_cli._local_capabilities")
    @patch("pipa_cli._request")
    def test_doctor_flags_a_stale_resident_contract(self, request, local_capabilities):
        current = self._doctor_capability_fixture()
        resident = self._doctor_capability_fixture()
        resident["commands"] = [{"id": "old_command"}]
        local_capabilities.return_value = current
        request.side_effect = [
            {"success": True, "pc": "online"},
            resident,
            {"success": True, "apps": {}, "contacts": {}, "integrations": {}},
            {"success": True, "commands": []},
            {"success": True, "protocol_version": 1, "tool_names": []},
            {"success": True, "checks": {}},
        ]

        result = pipa_cli._doctor("http://127.0.0.1:8765")

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["source_alignment"]["ok"])
        self.assertEqual(result["checks"]["source_alignment"]["reason"], "agent_reload_required")

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
        whatsapp_phone_open = pipa_cli._parser().parse_args(["whatsapp-phone-open", "+34600123456"])
        self.assertFalse(whatsapp_phone_open.confirm)
        discord_contact = pipa_cli._parser().parse_args(["discord-contact", "mama", "--confirm"])
        self.assertTrue(discord_contact.confirm)
        discord_call = pipa_cli._parser().parse_args(["discord-call", "mama", "--confirm"])
        self.assertTrue(discord_call.confirm)
        discord_call_channel = pipa_cli._parser().parse_args(
            ["discord-call-channel", "12345678901234567", "--confirm"]
        )
        self.assertTrue(discord_call_channel.confirm)

    def test_music_shortcuts_are_safe_commands_without_confirmation(self):
        for command in ("music-play", "music-next", "music-previous", "music-stop"):
            with self.subTest(command=command):
                arguments = pipa_cli._parser().parse_args([command])
                self.assertFalse(getattr(arguments, "confirm", False))

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
        self.assertTrue(result["arguments_valid"])
        self.assertTrue(result["requires_confirmation"])
        self.assertFalse(result["side_effects"])
        self.assertEqual(result["message"], "Buscar partida: ranked_solo")
        self.assertIn("matchmaking", result["description"])

    @patch("tools.agent_catalog.resolve_whatsapp_contact", side_effect=ValueError("missing local alias"))
    def test_intent_preview_reports_missing_local_configuration_without_executing(self, _resolve_contact):
        result = pipa_cli._preview_intent("prepara WhatsApp para mama y dile Hola")

        self.assertTrue(result["recognized"])
        self.assertEqual(result["tool_name"], "whatsapp_contact")
        self.assertFalse(result["arguments_valid"])
        self.assertTrue(result["requires_confirmation"])
        self.assertFalse(result["side_effects"])
        self.assertIn("configuración local", result["message"])

    def test_intent_preview_marks_safe_commands(self):
        result = pipa_cli._preview_intent("estado de matchmaking")

        self.assertEqual(result["tool_name"], "league_status")
        self.assertFalse(result["requires_confirmation"])


if __name__ == "__main__":
    unittest.main()
