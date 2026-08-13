import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.diagnostics import get_self_test  # noqa: E402
from tools.league import LeagueClientError  # noqa: E402

from backend.pipa_core.tools import ToolCatalog, ToolDefinition  # noqa: E402


class DiagnosticsTests(unittest.TestCase):
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_self_test_passes_without_optional_league_client(self, find_client):
        result = get_self_test(
            serial_gateway_configured=False,
            serial_gateway_running=False,
            serial_gateway_connected=False,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["checks"]["league_client"]["ready"])
        self.assertFalse(result["checks"]["serial_gateway"]["configured"])
        self.assertFalse(result["checks"]["serial_gateway"]["connected"])
        self.assertFalse(result["checks"]["url_builders"]["external_actions_executed"])
        self.assertEqual(result["checks"]["command_routes"]["recognized_commands"], 57)
        self.assertEqual(result["checks"]["command_routes"]["confirmation_gated_commands"], 39)
        self.assertEqual(result["checks"]["command_routes"]["structured_commands"], 19)
        self.assertGreater(result["checks"]["command_routes"]["direct_structured_commands"], 0)
        self.assertEqual(result["checks"]["command_routes"]["unpublished_tools"], 0)
        self.assertTrue(result["checks"]["secure_session"]["ok"])
        self.assertTrue(result["checks"]["secure_audio"]["ok"])
        self.assertTrue(result["checks"]["secure_audio"]["capture_gate"])
        self.assertTrue(result["checks"]["integration_adapters"]["ok"])
        self.assertEqual(result["checks"]["integration_adapters"]["url_builders_checked"], 8)
        self.assertTrue(result["checks"]["mobile_protocol"]["ok"])
        self.assertTrue(result["checks"]["mobile_protocol"]["result_redacted"])
        self.assertTrue(result["checks"]["device_protocol"]["ok"])
        self.assertTrue(result["checks"]["device_protocol"]["confirmation_gated"])
        self.assertTrue(result["checks"]["device_protocol"]["missing_touch_rejected"])
        self.assertTrue(result["checks"]["secure_serial_loopback"]["ok"])
        self.assertTrue(result["checks"]["secure_serial_loopback"]["confirmation_gated"])
        self.assertTrue(result["checks"]["secure_serial_loopback"]["result_redacted"])
        self.assertFalse(result["checks"]["secure_session"]["persistent_keys_touched"])
        self.assertEqual(result["checks"]["integration_policy"]["confirmation_mapped_tools"], 20)
        find_client.assert_called_once_with()

    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_configured_but_stopped_gateway_is_reported(self, _find_client):
        result = get_self_test(
            serial_gateway_configured=True,
            serial_gateway_running=False,
            serial_gateway_connected=False,
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["serial_gateway"]["ok"])

    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_configured_but_disconnected_gateway_fails_closed(self, _find_client):
        result = get_self_test(
            serial_gateway_configured=True,
            serial_gateway_running=True,
            serial_gateway_connected=False,
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["serial_gateway"]["ok"])

    @patch("tools.diagnostics.get_capabilities")
    def test_integration_policy_rejects_automatic_external_actions(self, get_capabilities):
        get_capabilities.return_value = {
            "integrations": {
                "apple_music": {"playback": True, "media_control": True},
                "whatsapp": {"send_message": False},
                "discord": {"start_call": False},
                "codex": {"writes_to_chat": False},
            }
        }

        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["integration_policy"]["ok"])

    @patch("tools.diagnostics.build_web_search_url", side_effect=ValueError("invalid"))
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_invalid_url_builder_fails_the_self_test(self, _find_client, _build_url):
        result = get_self_test(
            serial_gateway_configured=False,
            serial_gateway_running=False,
            serial_gateway_connected=False,
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["url_builders"]["ok"])

    @patch("tools.diagnostics.run_secure_self_test", side_effect=ValueError("invalid secure result"))
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_secure_session_failure_is_reported_without_leaking_details(self, _find_client, _secure_test):
        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["checks"]["secure_session"], {"ok": False, "code": "secure_session_invalid"})

    @patch("tools.diagnostics.parse_text_intent", return_value=None)
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_command_route_failure_is_reported_without_executing_actions(self, _find_client, _parse_intent):
        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["checks"]["command_routes"], {"ok": False, "code": "command_routes_invalid"})

    @patch(
        "tools.diagnostics.get_command_catalog",
        return_value=[
            {
                "id": "system_status",
                "tool_name": "system_status",
                "safety": "unsafe",
                "requires_confirmation": True,
            }
        ],
    )
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_command_catalog_safety_drift_is_reported(self, _find_client, _get_catalog):
        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["checks"]["command_routes"], {"ok": False, "code": "command_routes_invalid"})

    @patch(
        "tools.diagnostics.get_command_catalog",
        return_value=[
            {
                "id": "web_search",
                "tool_name": "web_search",
                "phrase": "busca <consulta>",
                "safety": "unsafe",
                "requires_confirmation": True,
            }
        ],
    )
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_structured_catalog_placeholder_drift_is_reported(self, _find_client, _get_catalog):
        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["checks"]["command_routes"], {"ok": False, "code": "command_routes_invalid"})

    @patch("tools.diagnostics.build_agent_catalog")
    @patch(
        "tools.diagnostics.get_command_catalog",
        return_value=[
            {
                "id": "system_status",
                "tool_name": "system_status",
                "safety": "safe",
                "requires_confirmation": False,
            }
        ],
    )
    @patch("tools.diagnostics.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_unpublished_agent_tool_is_reported(self, _find_client, _get_catalog, build_agent_catalog):
        build_agent_catalog.return_value = ToolCatalog(
            [
                ToolDefinition("system_status", lambda _arguments: {}),
                ToolDefinition("hidden_tool", lambda _arguments: {}),
            ]
        )

        result = get_self_test(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["checks"]["command_routes"], {"ok": False, "code": "command_routes_invalid"})


if __name__ == "__main__":
    unittest.main()
