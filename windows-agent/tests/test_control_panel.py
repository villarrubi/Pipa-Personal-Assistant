import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.apps import load_apps, save_apps  # noqa: E402
from tools.control_config import (  # noqa: E402
    get_command_preferences,
    get_whatsapp_settings,
    set_command_preference,
)
from tools.integration_catalog import get_command_catalog  # noqa: E402
from tools.timers import TimerManager  # noqa: E402
from tools.whatsapp import send_whatsapp_cloud_message  # noqa: E402

from backend.pipa_core.intents import parse_catalog_intent, parse_text_intent  # noqa: E402
from backend.pipa_core.tools import ToolRouter  # noqa: E402


class FakeCloudResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, _limit):
        return b'{"messages":[{"id":"private-id"}]}'


class ControlPanelTests(unittest.TestCase):
    def test_resident_agent_treats_disabled_catalog_tools_as_unavailable(self):
        self.assertTrue(main.pipa_core.command_catalog_authoritative)

    def test_control_panel_assets_are_local_and_present(self):
        response = main.control_panel()

        self.assertTrue(Path(response.path).is_file())
        self.assertTrue((main.CONTROL_UI_DIR / "pipa-control.css").is_file())
        self.assertTrue((main.CONTROL_UI_DIR / "pipa-control.js").is_file())

    def test_control_writes_need_explicit_confirmation_header(self):
        request = SimpleNamespace(
            method="PUT",
            headers={"x-pipa-local-request": "1"},
            url=SimpleNamespace(path="/control/processes"),
        )

        response = asyncio.run(main.protect_local_http(request, lambda _request: None))

        self.assertEqual(response.status_code, 403)
        self.assertIn("confirmación local", response.body.decode("utf-8"))

    @patch("main.get_whatsapp_public_status")
    @patch("main.get_command_control_catalog")
    @patch("main._control_processes")
    def test_overview_combines_process_command_and_automation_state(self, processes, commands, whatsapp):
        processes.return_value = [
            {"id": "one", "enabled": True},
            {"id": "two", "enabled": False},
        ]
        commands.return_value = [
            {"id": "first", "enabled": True},
            {"id": "second", "enabled": True},
        ]
        whatsapp.return_value = {"active": True}

        result = main.api_control_overview()

        self.assertEqual(result["summary"]["active_processes"], 1)
        self.assertEqual(result["summary"]["active_commands"], 2)
        self.assertTrue(result["summary"]["automatic_whatsapp"])

    @patch("main._control_processes")
    @patch("main.save_apps")
    @patch("main.load_apps")
    def test_process_editor_uses_the_execution_allowlist(self, load_apps_mock, save_apps_mock, processes):
        load_apps_mock.return_value = {"old": {"aliases": ["old"], "command": ["old.exe"], "enabled": True}}
        processes.return_value = [{"id": "new", "enabled": False}]

        result = main.api_control_save_process(
            main.ProcessControlRequest(
                id="new",
                original_id="old",
                aliases=["new", "nuevo"],
                launcher="new.exe",
                arguments=["--safe"],
                enabled=False,
            )
        )

        saved = save_apps_mock.call_args.args[0]
        self.assertNotIn("old", saved)
        self.assertEqual(saved["new"]["command"], ["new.exe", "--safe"])
        self.assertFalse(result["process"]["enabled"])

    def test_disabled_processes_are_not_executable_but_remain_editable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            with patch("tools.apps.LOCAL_APPS_FILE", path):
                save_apps(
                    {
                        "active": {"aliases": ["active"], "command": ["active.exe"]},
                        "paused": {
                            "aliases": ["paused"],
                            "command": ["paused.exe"],
                            "enabled": False,
                        },
                    }
                )
                self.assertEqual(set(load_apps()), {"active"})
                self.assertEqual(set(load_apps(include_disabled=True)), {"active", "paused"})

    def test_command_and_whatsapp_preferences_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control-panel.local.json"
            with patch("tools.control_config.LOCAL_CONTROL_FILE", path):
                set_command_preference("system_status", enabled=False, phrase="estado rápido")

                self.assertFalse(get_command_preferences()["system_status"]["enabled"])
                self.assertEqual(get_whatsapp_settings()["mode"], "manual")
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("token", json.dumps(stored).lower())

    @patch(
        "tools.integration_catalog.get_command_preferences",
        return_value={"system_status": {"enabled": False}, "system_power": {"phrase": "batería ahora"}},
    )
    @patch("tools.integration_catalog.whatsapp_automatic_send_active", return_value=False)
    def test_catalog_applies_disabled_state_and_edited_phrase(self, _automatic, _preferences):
        commands = get_command_catalog()
        command_ids = {command["id"] for command in commands}

        self.assertNotIn("system_status", command_ids)
        power = next(command for command in commands if command["id"] == "system_power")
        self.assertEqual(power["phrase"], "batería ahora")

    def test_new_process_voice_phrase_routes_through_open_app(self):
        intent = parse_text_intent("abre Photoshop")

        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool_name, "open_app")
        self.assertEqual(intent.arguments, {"app": "Photoshop"})

    def test_edited_catalog_phrase_builds_typed_arguments(self):
        intent = parse_catalog_intent(
            "volumen rápido 42",
            [
                {
                    "tool_name": "audio_volume",
                    "phrase": "volumen rápido <nivel>",
                    "parameters": [{"name": "percent", "kind": "integer", "max_length": 3}],
                }
            ],
        )

        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool_name, "audio_volume")
        self.assertEqual(intent.arguments, {"percent": 42})

    @patch("tools.whatsapp.request.urlopen", return_value=FakeCloudResponse())
    @patch("tools.whatsapp.get_whatsapp_access_token", return_value="secret-access-token-long-enough")
    @patch(
        "tools.whatsapp.get_whatsapp_settings",
        return_value={"mode": "cloud_api", "phone_number_id": "123456789", "api_version": "v23.0"},
    )
    def test_whatsapp_cloud_api_sends_without_returning_private_provider_data(
        self, _settings, _token, urlopen
    ):
        result = send_whatsapp_cloud_message("+34 600 123 456", "Hola")

        self.assertTrue(result["success"])
        self.assertTrue(result["sent"])
        self.assertFalse(result["requires_manual_send"])
        self.assertNotIn("private-id", str(result))
        cloud_request = urlopen.call_args.args[0]
        self.assertEqual(cloud_request.method, "POST")
        self.assertIn("/123456789/messages", cloud_request.full_url)

    @patch("main.send_whatsapp_cloud_message", return_value={"success": True, "sent": True})
    @patch("main.whatsapp_automatic_send_active", return_value=True)
    def test_whatsapp_route_uses_cloud_adapter_only_when_opted_in(self, _active, send_cloud):
        result = main.api_whatsapp_compose(main.WhatsAppRequest(phone="+34600123456", message="Hola"))

        self.assertTrue(result["sent"])
        send_cloud.assert_called_once_with("+34600123456", "Hola")

    @patch("tools.agent_catalog.send_whatsapp_cloud_message")
    @patch(
        "tools.agent_catalog.open_whatsapp_compose",
        return_value={"success": True, "sent": False},
    )
    @patch("tools.agent_catalog.whatsapp_automatic_send_active", return_value=False)
    def test_confirmation_freezes_manual_whatsapp_mode(self, automatic, open_compose, send_cloud):
        router = ToolRouter(build_agent_catalog(TimerManager()))
        pending = router.invoke(
            "whatsapp_compose",
            {"phone": "+34600123456", "message": "Hola"},
            owner_id="panel-test",
        )
        automatic.return_value = True

        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"],
            True,
            owner_id="panel-test",
        )

        self.assertFalse(result["result"]["sent"])
        open_compose.assert_called_once_with("+34600123456", "Hola")
        send_cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
