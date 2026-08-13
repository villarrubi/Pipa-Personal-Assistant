import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.capabilities import build_integration_capabilities  # noqa: E402
from tools.integration_catalog import get_command_catalog  # noqa: E402
from tools.security_policy import (  # noqa: E402
    CONFIRMATION_TOOL_PATHS,
    LOCAL_CONFIRMATION_PATHS,
)
from tools.timers import TimerManager  # noqa: E402

from backend.pipa_core.core import PipaCore  # noqa: E402


class IntegrationContractTests(unittest.TestCase):
    """Keep every outward-facing integration behind the same contract walls."""

    def setUp(self):
        self.catalog = build_agent_catalog(TimerManager())

    def test_every_unsafe_tool_has_a_local_route_and_device_confirmation_label(self):
        unsafe_tools = {name for name in self.catalog.names() if self.catalog.get(name).safety == "unsafe"}

        self.assertEqual(unsafe_tools, set(CONFIRMATION_TOOL_PATHS))
        self.assertEqual(set(CONFIRMATION_TOOL_PATHS.values()), set(LOCAL_CONFIRMATION_PATHS))
        for tool_name in unsafe_tools:
            self.assertNotEqual(
                PipaCore._device_confirmation_summary(tool_name),
                "Confirmar acción externa.",
            )

    def test_public_command_catalog_matches_the_real_router(self):
        commands = get_command_catalog()
        command_ids = [command["id"] for command in commands]

        self.assertEqual(len(command_ids), len(set(command_ids)))
        for command in commands:
            definition = self.catalog.get(command["tool_name"])
            self.assertEqual(command["safety"], definition.safety)
            self.assertEqual(
                command["requires_confirmation"],
                definition.safety == "unsafe",
            )

        expected_tools = {
            "web_search",
            "music_search",
            "whatsapp_compose",
            "whatsapp_contact",
            "discord_contact",
            "discord_call",
            "league_search",
            "open_codex",
        }
        self.assertTrue(expected_tools.issubset(self.catalog.names()))
        self.assertTrue(expected_tools.issubset({command["tool_name"] for command in commands}))

    def test_remote_capabilities_never_claim_automatic_private_actions(self):
        capabilities = build_integration_capabilities(
            apple_music_configured=True,
            league_available=True,
            league_ready=True,
            codex_configured=True,
            whatsapp_app_configured=True,
            discord_app_configured=True,
            whatsapp_contacts_configured=True,
            discord_contacts_configured=True,
        )

        self.assertFalse(capabilities["apple_music"]["playback"])
        self.assertTrue(capabilities["apple_music"]["requires_manual_selection"])
        self.assertFalse(capabilities["whatsapp"]["send_message"])
        self.assertTrue(capabilities["whatsapp"]["requires_manual_send"])
        self.assertFalse(capabilities["discord"]["start_call"])
        self.assertTrue(capabilities["discord"]["requires_manual_call"])
        self.assertFalse(capabilities["codex"]["writes_to_chat"])


if __name__ == "__main__":
    unittest.main()
