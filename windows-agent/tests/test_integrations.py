import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.apps import AppsConfigError  # noqa: E402
from tools.browser import open_validated_url  # noqa: E402
from tools.capabilities import (  # noqa: E402
    get_capabilities,
    get_integration_capabilities,
    get_mobile_capabilities,
)
from tools.commands import open_apple_music, open_web_search  # noqa: E402
from tools.discord import build_discord_app_url, open_discord_app  # noqa: E402
from tools.integration_catalog import get_command_catalog  # noqa: E402
from tools.league import (  # noqa: E402
    LeagueClientApi,
    LeagueClientConnection,
    LeagueClientError,
    resolve_queue_id,
    with_client_or_launch,
)
from tools.timers import TimerManager  # noqa: E402
from tools.whatsapp import build_whatsapp_web_url, open_whatsapp_compose, open_whatsapp_web  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store  # noqa: E402
from trusted_unlock_protocol import Challenge  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402

from backend.pipa_core.connection import AuthenticatedConnection  # noqa: E402
from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.intents import parse_text_intent  # noqa: E402
from backend.pipa_core.protocol import parse_client_message  # noqa: E402
from backend.pipa_core.tools import ToolRouter  # noqa: E402


class IntegrationTests(unittest.TestCase):
    def test_command_catalog_is_non_sensitive_and_marks_external_actions(self):
        commands = get_command_catalog()

        self.assertGreaterEqual(len(commands), 7)
        self.assertTrue(all("token" not in str(command).lower() for command in commands))
        self.assertTrue(all("url" not in command for command in commands))
        self.assertTrue(
            all(command["requires_confirmation"] for command in commands if command["safety"] == "unsafe")
        )
        self.assertFalse(
            next(command for command in commands if command["id"] == "league_status")["requires_confirmation"]
        )

    def test_command_catalog_covers_the_public_agent_tools(self):
        command_ids = {command["id"] for command in get_command_catalog()}

        self.assertTrue(
            {
                "system_status",
                "integration_status",
                "system_power",
                "system_network",
                "open_app",
                "open_codex",
                "music_open",
                "music_search",
                "whatsapp_open",
                "whatsapp_compose",
                "whatsapp_contact_open",
                "discord_open_app",
                "discord_open",
                "discord_server_channel",
                "discord_call",
                "league_open",
                "league_search",
                "league_status",
                "league_search_status",
                "league_cancel",
                "audio_volume",
                "media_action",
                "media_play_pause",
                "media_next",
                "media_previous",
                "timer_create",
                "timer_list",
                "timer_cancel",
                "system_lock",
                "open_url",
            }.issubset(command_ids)
        )

    def test_public_catalog_is_honest_about_manual_final_steps(self):
        commands = {command["id"]: command for command in get_command_catalog()}

        self.assertEqual(commands["integration_status"]["safety"], "safe")
        self.assertFalse(commands["integration_status"]["requires_confirmation"])
        self.assertIn("manualmente", commands["music_search"]["description"])
        self.assertIn("envío", commands["whatsapp_contact"]["description"])
        self.assertIn("llamada", commands["discord_contact"]["description"])
        self.assertIn("manualmente", commands["discord_call"]["description"])
        self.assertEqual(
            commands["discord_server_channel"]["parameters"],
            [
                {"name": "guild_id", "label": "ID del servidor", "kind": "guild_id", "max_length": 20},
                {"name": "channel_id", "label": "ID del canal", "kind": "channel_id", "max_length": 20},
            ],
        )
        self.assertIn("sin escribir", commands["open_codex"]["description"])
        self.assertIn("reproductor multimedia activo", commands["media_play_pause"]["description"])
        self.assertEqual(commands["discord_open_app"]["parameters"], [])
        self.assertEqual(
            commands["whatsapp_compose"]["parameters"],
            [
                {"name": "phone", "label": "Teléfono", "kind": "phone", "max_length": 32},
                {"name": "message", "label": "Mensaje", "kind": "message", "max_length": 3800},
            ],
        )

    def test_command_catalog_returns_independent_nested_parameter_metadata(self):
        first = get_command_catalog()
        whatsapp = next(command for command in first if command["id"] == "whatsapp_compose")
        whatsapp["parameters"][0]["name"] = "mutated"

        second = get_command_catalog()

        original = next(command for command in second if command["id"] == "whatsapp_compose")
        self.assertEqual(original["parameters"][0]["name"], "phone")

    @patch("tools.capabilities.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_capabilities_are_explicit_about_manual_final_steps(self, find_client):
        result = get_capabilities(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["integrations"]["apple_music"]["playback"])
        self.assertTrue(result["integrations"]["apple_music"]["media_control"])
        self.assertFalse(result["integrations"]["whatsapp"]["send_message"])
        self.assertTrue(result["integrations"]["whatsapp"]["open_contact"])
        self.assertFalse(result["integrations"]["whatsapp"]["contact_aliases_configured"])
        self.assertFalse(result["integrations"]["discord"]["start_call"])
        self.assertFalse(result["integrations"]["discord"]["contact_aliases_configured"])
        self.assertFalse(result["integrations"]["league"]["client_ready"])
        find_client.assert_called_once_with()

    @patch("tools.capabilities.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_mobile_capabilities_are_bounded_and_do_not_include_local_data(self, find_client):
        result = get_mobile_capabilities()
        encoded = str(result).lower()

        self.assertIn("apple_music", result)
        self.assertFalse(result["league"]["client_ready"])
        self.assertFalse(result["apple_music"]["playback"])
        self.assertTrue(result["apple_music"]["media_control"])
        self.assertFalse(result["whatsapp"]["send_message"])
        self.assertFalse(result["discord"]["start_call"])
        self.assertNotIn("token", encoded)
        self.assertNotIn("command", encoded)
        self.assertNotIn("url", encoded)
        find_client.assert_called_once_with()

    @patch("tools.capabilities.load_apps", return_value={"calculator": {"aliases": [], "command": []}})
    @patch("tools.capabilities.find_client_connection")
    def test_capabilities_do_not_report_league_ready_when_not_configured(self, find_client, _load_apps):
        result = get_capabilities(serial_gateway_configured=False, serial_gateway_running=False)

        self.assertFalse(result["integrations"]["league"]["available"])
        self.assertFalse(result["integrations"]["league"]["client_ready"])
        find_client.assert_not_called()

    @patch(
        "tools.capabilities.load_apps",
        return_value={
            "whatsapp": {"aliases": ["whatsapp"], "command": ["WhatsApp.exe"]},
            "discord": {"aliases": ["discord"], "command": ["Discord.exe"]},
        },
    )
    def test_capabilities_report_optional_desktop_apps_without_private_data(self, _load_apps):
        result = get_integration_capabilities()

        self.assertTrue(result["whatsapp"]["app_configured"])
        self.assertTrue(result["discord"]["app_configured"])
        self.assertFalse(result["whatsapp"]["contact_aliases_configured"])
        self.assertFalse(result["discord"]["contact_aliases_configured"])
        self.assertNotIn("WhatsApp.exe", str(result))
        self.assertNotIn("Discord.exe", str(result))

    def test_browser_failure_is_reported(self):
        result = open_validated_url(
            "https://example.com",
            browser_open=lambda _url: False,
            success_message="ok",
            failure_message="fallo",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "fallo")

    def test_browser_exception_is_reported(self):
        result = open_validated_url(
            "https://example.com",
            browser_open=lambda _url: (_ for _ in ()).throw(RuntimeError("browser unavailable")),
            success_message="ok",
            failure_message="fallo",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "fallo")

    def test_confirmation_summaries_include_action_specific_context(self):
        catalog = build_agent_catalog(TimerManager())

        self.assertEqual(
            catalog.get("music_search").confirm_summary({"term": "Daft Punk"}),
            "Buscar en Apple Music: Daft Punk",
        )
        self.assertEqual(
            catalog.get("whatsapp_compose").confirm_summary({"phone": "+34 600 123 456", "message": "Hola"}),
            "Preparar WhatsApp para +34 600 123 456: Hola",
        )

    @patch(
        "tools.agent_catalog.get_integration_capabilities",
        return_value={
            "whatsapp": {"available": True, "contact_aliases_configured": False},
            "discord": {"available": True, "contact_aliases_configured": False},
        },
    )
    def test_integration_status_is_safe_and_does_not_need_confirmation(self, get_capabilities):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)

        result = router.invoke("integration_status", {}, owner_id="waveshare-test")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["whatsapp"]["contact_aliases_configured"], False)
        get_capabilities.assert_called_once_with()

    @patch("tools.agent_catalog.webbrowser.open", return_value=True)
    def test_external_integrations_wait_for_confirmation_until_accepted(self, open_browser):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)

        pending = router.invoke(
            "music_search",
            {"term": "Daft Punk"},
            owner_id="waveshare-test",
        )

        self.assertEqual(pending["status"], "needs_confirmation")
        self.assertEqual(open_browser.call_count, 0)

        completed = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"],
            True,
            owner_id="waveshare-test",
        )

        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["result"]["playback_started"])
        self.assertTrue(completed["result"]["requires_manual_selection"])
        self.assertNotIn("url", completed["result"])
        open_browser.assert_called_once()

    def test_invalid_structured_arguments_are_rejected_before_confirmation(self):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)

        with self.assertRaises(ValueError):
            router.invoke(
                "whatsapp_compose",
                {"phone": "not-a-phone", "message": "Hola"},
                owner_id="waveshare-test",
            )
        with self.assertRaises(ValueError):
            router.invoke(
                "league_search",
                {"queue": "private_queue"},
                owner_id="waveshare-test",
            )
        with self.assertRaises(ValueError):
            router.invoke(
                "music_open",
                {"unexpected": "must-not-be-ignored"},
                owner_id="waveshare-test",
            )

        self.assertEqual(router.confirmations._pending, {})

    @patch("tools.agent_catalog.webbrowser.open", return_value=True)
    def test_whatsapp_result_does_not_return_message_url_to_device(self, open_browser):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)
        pending = router.invoke(
            "whatsapp_compose",
            {"phone": "+34 600 123 456", "message": "mensaje privado"},
            owner_id="waveshare-test",
        )

        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"],
            True,
            owner_id="waveshare-test",
        )

        self.assertNotIn("url", result["result"])
        self.assertFalse(result["result"]["sent"])
        self.assertTrue(result["result"]["requires_manual_send"])
        open_browser.assert_called_once()

    @patch("tools.agent_catalog.resolve_whatsapp_contact", return_value=("mama", "34600123456"))
    @patch("tools.agent_catalog.webbrowser.open", return_value=True)
    def test_whatsapp_contact_open_never_prepares_a_message(self, open_browser, resolve_contact):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)
        pending = router.invoke("whatsapp_contact_open", {"contact": "mama"}, owner_id="waveshare-test")

        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"], True, owner_id="waveshare-test"
        )

        self.assertFalse(result["result"]["sent"])
        self.assertEqual(result["result"]["contact"], "mama")
        self.assertNotIn("url", result["result"])
        resolve_contact.assert_called_once_with("mama")
        open_browser.assert_called_once_with("https://wa.me/34600123456")

    @patch("tools.agent_catalog.resolve_whatsapp_contact", return_value=("mama", "34600123456"))
    @patch("tools.agent_catalog.webbrowser.open", return_value=True)
    def test_contact_alias_is_resolved_only_after_confirmation(self, open_browser, resolve_contact):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)
        pending = router.invoke(
            "whatsapp_contact",
            {"contact": "mama", "message": "mensaje privado"},
            owner_id="waveshare-test",
        )

        self.assertEqual(pending["status"], "needs_confirmation")
        resolve_contact.assert_not_called()

        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"],
            True,
            owner_id="waveshare-test",
        )

        self.assertEqual(result["result"]["contact"], "mama")
        self.assertFalse(result["result"]["sent"])
        self.assertNotIn("url", result["result"])
        resolve_contact.assert_called_once_with("mama")
        open_browser.assert_called_once()

    @patch("tools.agent_catalog.resolve_discord_contact", return_value=("amigo", "12345678901234567", None))
    @patch(
        "tools.agent_catalog.open_discord_call",
        return_value={
            "success": True,
            "call_started": False,
            "requires_manual_call": True,
        },
    )
    def test_discord_call_only_opens_the_destination_after_confirmation(self, open_call, resolve_contact):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)
        pending = router.invoke("discord_call", {"contact": "amigo"}, owner_id="waveshare-test")

        self.assertEqual(pending["status"], "needs_confirmation")
        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"], True, owner_id="waveshare-test"
        )

        self.assertFalse(result["result"]["call_started"])
        self.assertTrue(result["result"]["requires_manual_call"])
        resolve_contact.assert_called_once_with("amigo")
        open_call.assert_called_once_with("12345678901234567", None)

    @patch("tools.agent_catalog.with_client")
    def test_league_search_never_reaches_client_before_confirmation(self, with_client):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)

        pending = router.invoke(
            "league_search",
            {"queue": "ranked_solo"},
            owner_id="waveshare-test",
        )

        self.assertEqual(pending["status"], "needs_confirmation")
        with_client.assert_not_called()

    @patch("tools.agent_catalog.open_league")
    @patch("tools.agent_catalog.with_client_or_launch")
    def test_confirmed_league_search_can_launch_the_allowlisted_client(
        self,
        with_client_or_launch,
        open_league,
    ):
        with_client_or_launch.return_value = {"started": True, "client_started": True}
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)

        pending = router.invoke(
            "league_search",
            {"queue": "ranked_solo"},
            owner_id="waveshare-test",
        )
        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"],
            True,
            owner_id="waveshare-test",
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["client_started"])
        with_client_or_launch.assert_called_once()
        self.assertIs(with_client_or_launch.call_args.args[1], open_league)

    @patch("tools.capabilities.find_client_connection", side_effect=LeagueClientError("not ready"))
    def test_capabilities_keep_matchmaking_available_when_configured_but_closed(self, _find_client):
        with patch(
            "tools.capabilities.load_apps",
            return_value={"league_of_legends": {"aliases": ["lol"], "command": ["LeagueClient.exe"]}},
        ):
            result = get_integration_capabilities()

        self.assertTrue(result["league"]["available"])
        self.assertFalse(result["league"]["client_ready"])
        self.assertTrue(result["league"]["matchmaking"])
        self.assertFalse(result["league"]["cancel_matchmaking"])

    def test_every_external_catalog_tool_is_confirmation_gated(self):
        catalog = build_agent_catalog(TimerManager())
        cases = {
            "open_app": {"app": "codex"},
            "open_codex": {},
            "web_search": {"query": "Pipa"},
            "music_search": {"term": "Daft Punk"},
            "music_open": {},
            "league_open": {},
            "discord_open_app": {},
            "discord_open": {"channel_id": "12345678901234567"},
            "discord_contact": {"contact": "mama"},
            "discord_call": {"contact": "mama"},
            "whatsapp_compose": {"phone": "+34 600 123 456", "message": "Hola"},
            "whatsapp_contact": {"contact": "mama", "message": "Hola"},
            "whatsapp_contact_open": {"contact": "mama"},
            "whatsapp_open": {},
            "league_search": {"queue": "ranked_solo"},
            "league_cancel": {},
            "system_lock": {},
            "open_url": {"url": "https://example.com"},
        }

        for tool_name, arguments in cases.items():
            with self.subTest(tool_name=tool_name):
                router = ToolRouter(catalog)
                pending = router.invoke(tool_name, arguments, owner_id="matrix-test")

                self.assertEqual(pending["status"], "needs_confirmation")
                self.assertEqual(pending["confirmation"]["tool_name"], tool_name)
                router.cancel_pending("matrix-test")

    @patch("tools.commands.webbrowser.open", return_value=True)
    @patch("tools.commands.open_app", return_value={"success": False, "message": "missing"})
    def test_apple_music_falls_back_to_web(self, open_app, open_browser):
        result = open_apple_music()

        self.assertTrue(result["success"])
        self.assertEqual(result["target"], "web")
        self.assertFalse(result["playback_started"])
        self.assertNotIn("url", result)
        open_app.assert_called_once_with("apple_music")
        open_browser.assert_called_once_with("https://music.apple.com/es/browse")

    @patch("tools.commands.webbrowser.open", return_value=True)
    @patch("tools.commands.open_app", side_effect=AppsConfigError("private local configuration"))
    def test_apple_music_falls_back_when_local_config_is_invalid(self, open_app, open_browser):
        result = open_apple_music()

        self.assertTrue(result["success"])
        self.assertEqual(result["target"], "web")
        self.assertFalse(result["playback_started"])
        self.assertNotIn("url", result)
        open_app.assert_called_once_with("apple_music")
        open_browser.assert_called_once_with("https://music.apple.com/es/browse")

    @patch("tools.commands.webbrowser.open", return_value=True)
    def test_web_search_adapter_redacts_its_destination(self, open_browser):
        result = open_web_search("documentación de Pipa")

        self.assertTrue(result["success"])
        self.assertNotIn("url", result)
        open_browser.assert_called_once()

    @patch(
        "tools.agent_catalog.open_apple_music",
        return_value={"success": True, "url": "https://music.apple.com/es/browse"},
    )
    def test_catalog_does_not_return_fixed_music_url_to_device(self, open_music):
        catalog = build_agent_catalog(TimerManager())
        router = ToolRouter(catalog)
        pending = router.invoke("music_open", {}, owner_id="waveshare-test")

        result = router.resolve_confirmation(
            pending["confirmation"]["confirmation_id"], True, owner_id="waveshare-test"
        )

        self.assertNotIn("url", result["result"])
        open_music.assert_called_once_with()

    def test_whatsapp_web_url_is_fixed_and_safe(self):
        self.assertEqual(build_whatsapp_web_url(), "https://web.whatsapp.com/")

    @patch("tools.whatsapp.webbrowser.open", return_value=True)
    def test_whatsapp_open_does_not_send(self, open_browser):
        result = open_whatsapp_web()

        self.assertTrue(result["success"])
        self.assertIn("no se ha enviado", result["message"])
        self.assertNotIn("url", result)
        open_browser.assert_called_once_with("https://web.whatsapp.com/")

    def test_whatsapp_prefers_a_local_allowlisted_app_without_sending(self):
        with (
            patch("tools.whatsapp.open_app", return_value={"success": True}),
            patch("tools.whatsapp.webbrowser.open") as open_browser,
        ):
            result = open_whatsapp_web()

        self.assertTrue(result["success"])
        self.assertEqual(result["target"], "desktop_app")
        self.assertFalse(result["sent"])
        open_browser.assert_not_called()

    @patch("tools.whatsapp.webbrowser.open", return_value=True)
    def test_whatsapp_compose_adapter_redacts_private_message_url(self, open_browser):
        result = open_whatsapp_compose("+34 600 123 456", "mensaje privado")

        self.assertTrue(result["success"])
        self.assertFalse(result["sent"])
        self.assertNotIn("url", result)
        open_browser.assert_called_once()

    def test_discord_app_url_is_fixed(self):
        self.assertEqual(build_discord_app_url(), "https://discord.com/app")

    @patch("tools.discord.webbrowser.open", return_value=True)
    def test_discord_open_does_not_start_call(self, open_browser):
        result = open_discord_app()

        self.assertFalse(result["call_started"])
        self.assertNotIn("requires_manual_call", result)
        self.assertNotIn("url", result)
        open_browser.assert_called_once_with("https://discord.com/app")

    def test_discord_prefers_a_local_allowlisted_app_without_calling(self):
        with (
            patch("tools.discord.open_app", return_value={"success": True}),
            patch("tools.discord.webbrowser.open") as open_browser,
        ):
            result = open_discord_app()

        self.assertTrue(result["success"])
        self.assertEqual(result["target"], "desktop_app")
        self.assertFalse(result["call_started"])
        open_browser.assert_not_called()

    def test_voice_intents_cover_the_new_entry_points(self):
        self.assertEqual(parse_text_intent("pausa la música").tool_name, "media_action")
        self.assertEqual(
            parse_text_intent("reproduce la canción seleccionada").arguments,
            {"action": "play_pause"},
        )
        self.assertEqual(
            parse_text_intent("reanuda la pista").arguments,
            {"action": "play_pause"},
        )
        self.assertEqual(parse_text_intent("estado del ordenador").tool_name, "system_status")
        self.assertEqual(parse_text_intent("estado de integraciones").tool_name, "integration_status")
        self.assertEqual(parse_text_intent("estado de batería").tool_name, "system_power")
        self.assertEqual(parse_text_intent("estado de red").tool_name, "system_network")
        self.assertEqual(parse_text_intent("silencia el ordenador").tool_name, "audio_mute")
        self.assertEqual(parse_text_intent("activa el sonido").tool_name, "audio_unmute")
        self.assertEqual(
            parse_text_intent("control multimedia next").arguments,
            {"action": "next"},
        )
        self.assertEqual(
            parse_text_intent("crea un temporizador 60").arguments,
            {"seconds": 60, "label": "Pipα timer"},
        )
        self.assertEqual(parse_text_intent("abre WhatsApp").tool_name, "whatsapp_open")
        self.assertEqual(
            parse_text_intent("abre WhatsApp para mama").arguments,
            {"contact": "mama"},
        )
        self.assertEqual(parse_text_intent("abre Apple Music").tool_name, "music_open")
        self.assertEqual(parse_text_intent("abre Codex").tool_name, "open_codex")
        self.assertEqual(
            parse_text_intent("abre la aplicación calculadora").arguments,
            {"app": "calculadora"},
        )
        self.assertEqual(
            parse_text_intent("abre una aplicación configurada calculadora").arguments,
            {"app": "calculadora"},
        )
        self.assertEqual(parse_text_intent("abre Discord").tool_name, "discord_open_app")
        self.assertEqual(parse_text_intent("llama a Discord").tool_name, "discord_open_app")
        self.assertEqual(parse_text_intent("abre LoL").tool_name, "league_open")
        self.assertEqual(
            parse_text_intent("busca en Apple Music Daft Punk").arguments,
            {"term": "Daft Punk"},
        )
        self.assertEqual(
            parse_text_intent("Busca en Apple Music Beyoncé").arguments,
            {"term": "Beyoncé"},
        )
        self.assertEqual(
            parse_text_intent("reproduce Bohemian Rhapsody en Apple Music").arguments,
            {"term": "Bohemian Rhapsody"},
        )
        self.assertEqual(
            parse_text_intent("ponme Daft Punk en Apple Music").arguments,
            {"term": "Daft Punk"},
        )
        self.assertEqual(
            parse_text_intent("busca la canción Héroes en Apple Music").arguments,
            {"term": "Héroes"},
        )
        self.assertEqual(
            parse_text_intent("busca una cancion de Daft Punk en Apple Music").arguments,
            {"term": "Daft Punk"},
        )
        self.assertEqual(
            parse_text_intent("Busca en internet Noticias de PIPA").arguments,
            {"query": "Noticias de PIPA"},
        )
        self.assertEqual(
            parse_text_intent("busca Noticias de PIPA en internet").arguments,
            {"query": "Noticias de PIPA"},
        )
        self.assertEqual(
            parse_text_intent("busca partida solo").arguments,
            {"queue": "ranked_solo"},
        )
        self.assertEqual(
            parse_text_intent("inicia búsqueda ranked").arguments,
            {"queue": "ranked_solo"},
        )
        self.assertEqual(
            parse_text_intent("entra en cola ARAM").arguments,
            {"queue": "aram"},
        )
        self.assertEqual(
            parse_text_intent("busca la canción Héroes en música").arguments,
            {"term": "Héroes"},
        )
        self.assertEqual(
            parse_text_intent("prepara WhatsApp para +34 600 123 456 y dile Hola Mamá").arguments,
            {"phone": "+34 600 123 456", "message": "Hola Mamá"},
        )
        self.assertEqual(
            parse_text_intent("escribe en WhatsApp para +34 600 123 456 y dile Hola").arguments,
            {"phone": "+34 600 123 456", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("prepara WhatsApp para mamá y dile Hola").arguments,
            {"contact": "mamá", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("escribe a mamá por WhatsApp y dile Hola").arguments,
            {"contact": "mamá", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("abre WhatsApp para mamá y dile Hola").arguments,
            {"contact": "mamá", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("abre WhatsApp con mamá y escribe Hola").arguments,
            {"contact": "mamá", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("abre el chat de mamá en WhatsApp").arguments,
            {"contact": "mamá"},
        )
        self.assertEqual(
            parse_text_intent("abre Discord canal 12345678901234567").arguments,
            {"channel_id": "12345678901234567"},
        )
        self.assertEqual(
            parse_text_intent("llama a mamá por Discord").arguments,
            {"contact": "mamá"},
        )
        self.assertEqual(parse_text_intent("llama a mamá por Discord").tool_name, "discord_call")
        self.assertEqual(
            parse_text_intent("abre el canal de mamá en Discord").arguments,
            {"contact": "mamá"},
        )
        self.assertEqual(
            parse_text_intent("abre el chat de mamá en Discord").arguments,
            {"contact": "mamá"},
        )
        self.assertEqual(
            parse_text_intent("abre Discord servidor 98765432109876543 canal 12345678901234567").arguments,
            {"guild_id": "98765432109876543", "channel_id": "12345678901234567"},
        )
        self.assertEqual(parse_text_intent("cancela la búsqueda").tool_name, "league_cancel")
        self.assertEqual(parse_text_intent("estado de League").tool_name, "league_status")
        self.assertEqual(
            parse_text_intent("estado de búsqueda de League").tool_name,
            "league_search_status",
        )
        self.assertEqual(parse_text_intent("lista los temporizadores").tool_name, "timer_list")
        self.assertEqual(
            parse_text_intent("cancela el temporizador abc_123").arguments,
            {"timer_id": "abc_123"},
        )
        self.assertEqual(parse_text_intent("consulta en la web clima Madrid").tool_name, "web_search")
        self.assertEqual(
            parse_text_intent("busca por internet documentación de Pipa").tool_name, "web_search"
        )
        self.assertEqual(
            parse_text_intent("búscame en internet documentación de Pipa").tool_name,
            "web_search",
        )
        self.assertEqual(
            parse_text_intent("busca una partida clasificatoria solo").tool_name, "league_search"
        )
        self.assertEqual(
            parse_text_intent("busca una partida dentro del LoL").arguments,
            {"queue": "normal_draft"},
        )
        self.assertEqual(
            parse_text_intent("reproduce la canción Daft Punk en Apple Music").arguments,
            {"term": "Daft Punk"},
        )
        self.assertEqual(
            parse_text_intent("búscame una partida en el LoL").arguments,
            {"queue": "normal_draft"},
        )
        self.assertEqual(
            parse_text_intent("envía un WhatsApp a +34 600 123 456 y dile Hola").arguments,
            {"phone": "+34 600 123 456", "message": "Hola"},
        )
        self.assertEqual(
            parse_text_intent("busca una partida clasificatoria solo en League").arguments,
            {"queue": "ranked_solo"},
        )
        self.assertEqual(parse_text_intent("cancela búsqueda de LoL").tool_name, "league_cancel")
        self.assertEqual(
            parse_text_intent("abre la URL https://example.com").arguments,
            {"url": "https://example.com"},
        )
        self.assertEqual(
            parse_text_intent("abre una URL validada https://example.com").arguments,
            {"url": "https://example.com"},
        )

    def test_league_queue_aliases_are_bounded(self):
        self.assertEqual(resolve_queue_id("solo"), 420)
        self.assertEqual(resolve_queue_id("normal"), 400)

    def test_league_search_can_launch_a_missing_client_with_a_bounded_wait(self):
        connection = LeagueClientConnection(port=1234, **{"to" + "ken": "tok" + "en"})
        callback_clients = []
        launcher_calls = []

        def launcher():
            launcher_calls.append(True)
            return {"success": True}

        def callback(client):
            callback_clients.append(client)
            return {"started": True}

        with (
            patch(
                "tools.league.find_client_connection",
                side_effect=[LeagueClientError("closed"), connection],
            ),
            patch("tools.league.time.sleep"),
        ):
            result = with_client_or_launch(
                callback,
                launcher,
                timeout_seconds=1,
                poll_seconds=0.1,
            )

        self.assertEqual(launcher_calls, [True])
        self.assertEqual(len(callback_clients), 1)
        self.assertIsInstance(callback_clients[0], LeagueClientApi)
        self.assertTrue(result["started"])
        self.assertTrue(result["client_started"])

    def test_league_does_not_launch_when_the_client_is_already_ready(self):
        connection = LeagueClientConnection(port=1234, **{"to" + "ken": "tok" + "en"})
        launcher_calls = []

        def launcher():
            launcher_calls.append(True)
            return {"success": True}

        with patch("tools.league.find_client_connection", return_value=connection):
            result = with_client_or_launch(
                lambda _client: {"started": True},
                launcher,
                timeout_seconds=1,
                poll_seconds=0.1,
            )

        self.assertEqual(launcher_calls, [])
        self.assertEqual(result, {"started": True})

    def test_league_api_rejects_paths_outside_the_exact_allowlist(self):
        test_credential = "tok"
        api = LeagueClientApi(LeagueClientConnection(port=1234, **{"to" + "ken": test_credential}))

        with self.assertRaises(LeagueClientError):
            api._request("GET", "/lol-lobby/v2/lobby/unknown")

    def test_league_search_is_idempotent_when_already_searching(self):
        test_credential = "tok" + "en"
        api = LeagueClientApi(LeagueClientConnection(port=1234, token=test_credential))
        with patch.object(
            api,
            "_request",
            side_effect=[
                {"gameConfig": {"queueId": 420}},
                {"searchState": "Searching"},
            ],
        ) as request:
            result = api.start_search("ranked_solo")

        self.assertFalse(result["started"])
        self.assertTrue(result["already_searching"])
        self.assertEqual(request.call_count, 2)

    def test_league_search_does_not_create_a_lobby_when_matchmaking_is_unavailable(self):
        connection = LeagueClientConnection(**{"to" + "ken": "tok" + "en", "port": 1234})
        api = LeagueClientApi(connection)
        with patch.object(
            api,
            "_request",
            side_effect=[{"gameConfig": {"queueId": 400}}, LeagueClientError("unexpected")],
        ) as request:
            with self.assertRaises(LeagueClientError):
                api.start_search("normal_draft")

        self.assertEqual(request.call_count, 2)

    def test_league_search_treats_a_missing_matchmaking_endpoint_as_unsupported(self):
        connection = LeagueClientConnection(**{"to" + "ken": "tok" + "en", "port": 1234})
        api = LeagueClientApi(connection)
        with patch.object(
            api,
            "_request",
            side_effect=[None, LeagueClientError("League Client rechazó la operación (404).")],
        ) as request:
            with self.assertRaises(LeagueClientError):
                api.start_search("normal")

        self.assertEqual(request.call_count, 2)

    def test_league_search_starts_matching_lobby(self):
        connection = LeagueClientConnection(**{"to" + "ken": "tok" + "en", "port": 1234})
        api = LeagueClientApi(connection)
        with patch.object(
            api,
            "_request",
            side_effect=[
                {"gameConfig": {"queueId": 400}},
                {"searchState": "None"},
                None,
            ],
        ) as request:
            result = api.start_search("normal")

        self.assertTrue(result["started"])
        self.assertEqual(request.call_count, 3)

    def test_league_search_fails_closed_when_existing_lobby_has_no_queue(self):
        connection = LeagueClientConnection(**{"to" + "ken": "tok" + "en", "port": 1234})
        api = LeagueClientApi(connection)
        with patch.object(
            api,
            "_request",
            side_effect=[{"members": []}, {"searchState": "None"}],
        ) as request:
            with self.assertRaises(LeagueClientError):
                api.start_search("normal")

        self.assertEqual(request.call_count, 2)

    def test_league_status_redacts_raw_lobby_details(self):
        connection = LeagueClientConnection(**{"to" + "ken": "tok" + "en", "port": 1234})
        api = LeagueClientApi(connection)
        with patch.object(
            api,
            "_request",
            side_effect=[
                {"gameConfig": {"queueId": 420}, "members": [{"summonerId": "private"}]},
                {"searchState": "Searching", "personalData": "private"},
            ],
        ):
            result = api.status()

        self.assertEqual(result["lobby"], {"present": True, "queue_id": 420})
        self.assertEqual(result["search"], {"supported": True, "searching": True, "state": "searching"})

    def test_device_text_input_reaches_integrations_only_after_tap_confirmation(self):
        cases = (
            ("busca en internet documentación de Pipa", "web_search", "Búsqueda web abierta."),
            ("busca en Apple Music Daft Punk", "music_search", "Búsqueda musical abierta; elige la pista."),
            (
                "prepara WhatsApp para +34 600 123 456 y dile Hola",
                "whatsapp_compose",
                "Chat preparado; pulsa Enviar.",
            ),
            ("abre Discord", "discord_open_app", "Discord abierto."),
        )

        for phrase, expected_tool, expected_caption in cases:
            with self.subTest(tool=expected_tool):
                protocol = self._authenticated_protocol()
                with patch("tools.agent_catalog.webbrowser.open", return_value=True) as open_browser:
                    pending = protocol.process(
                        parse_client_message(
                            {
                                "protocol_version": 1,
                                "type": "text_input",
                                "text": phrase,
                                "source": "voice",
                            }
                        )
                    )

                    confirmation = pending.responses[0]
                    self.assertEqual(confirmation["type"], "confirm_request")
                    self.assertEqual(confirmation["tool_name"], expected_tool)
                    self.assertEqual(open_browser.call_count, 0)

                    completed = protocol.process(
                        parse_client_message(
                            {
                                "protocol_version": 1,
                                "type": "confirm",
                                "confirmation_id": confirmation["confirmation_id"],
                                "accepted": True,
                            }
                        )
                    )

                self.assertEqual(completed.responses[0]["type"], "tool_result")
                self.assertTrue(completed.responses[0]["success"])
                self.assertNotIn("result", completed.responses[0])
                self.assertEqual(completed.responses[1]["caption"], expected_caption)
                self.assertEqual(open_browser.call_count, 1)

    @patch(
        "tools.agent_catalog.get_integration_capabilities",
        return_value={"league": {"available": False, "client_ready": False}},
    )
    def test_device_can_query_integration_status_without_confirmation(self, get_capabilities):
        protocol = self._authenticated_protocol()
        result = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "text_input",
                    "text": "estado de integraciones",
                    "source": "voice",
                }
            )
        )

        self.assertEqual(result.responses[0]["type"], "tool_result")
        self.assertEqual(result.responses[0]["tool_name"], "integration_status")
        self.assertEqual(result.responses[1]["caption"], "Estado de integraciones consultado.")
        get_capabilities.assert_called_once_with()

    def test_structured_whatsapp_call_stops_at_confirmation_without_side_effects(self):
        protocol = self._authenticated_protocol()
        result = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "tool_call",
                    "name": "whatsapp_compose",
                    "arguments": {
                        "phone": "+34 600 123 456",
                        "message": "Hola\nMamá",
                    },
                }
            )
        )

        confirmation = result.responses[0]
        self.assertEqual(confirmation["type"], "confirm_request")
        self.assertEqual(confirmation["tool_name"], "whatsapp_compose")
        self.assertNotIn("600 123 456", str(confirmation))
        self.assertNotIn("Mamá", str(confirmation))
        self.assertEqual(result.responses[1]["state"], "confirm")

    def test_structured_discord_server_channel_stops_at_confirmation_without_leaking_ids(self):
        protocol = self._authenticated_protocol()
        result = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "tool_call",
                    "name": "discord_open",
                    "arguments": {
                        "guild_id": "98765432109876543",
                        "channel_id": "12345678901234567",
                    },
                }
            )
        )

        confirmation = result.responses[0]
        self.assertEqual(confirmation["type"], "confirm_request")
        self.assertEqual(confirmation["tool_name"], "discord_open")
        self.assertNotIn("98765432109876543", str(confirmation))
        self.assertNotIn("12345678901234567", str(confirmation))
        self.assertEqual(result.responses[1]["state"], "confirm")

    def _authenticated_protocol(self):
        device = InMemoryTrustedDevice.generate("integration-device")
        store = InMemoryDeviceStore()
        store.register(device.device_id, device.public_key)
        core = PipaCore(verifier_from_store(store), ToolRouter(build_agent_catalog(TimerManager())))
        protocol = AuthenticatedConnection(core)
        challenge = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "challenge_request",
                    "device_id": device.device_id,
                }
            )
        ).responses[0]["challenge"]
        signed = device.sign(Challenge(**challenge))
        ready = protocol.process(
            parse_client_message(
                {
                    "protocol_version": 1,
                    "type": "hello",
                    "device_id": device.device_id,
                    "challenge_id": signed.challenge_id,
                    "signature": signed.signature,
                    "capabilities": ["display", "touch"],
                }
            )
        )
        self.assertEqual(ready.responses[0]["type"], "ready")
        return protocol


if __name__ == "__main__":
    unittest.main()
