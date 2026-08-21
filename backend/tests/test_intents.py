import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from tools.agent_catalog import build_agent_catalog  # noqa: E402
from tools.timers import TimerManager  # noqa: E402

from backend.pipa_core.intents import (  # noqa: E402
    parse_catalog_intent,
    parse_text_intent,
    parse_voice_intent,
    split_voice_wake_phrase,
)


class IntegrationIntentTests(unittest.TestCase):
    def assert_intent(self, text, tool_name, arguments):
        intent = parse_text_intent(text)
        self.assertIsNotNone(intent, text)
        self.assertEqual(intent.tool_name, tool_name)
        self.assertEqual(intent.arguments, arguments)

    def test_voice_wake_phrase_accepts_dictation_punctuation_and_keeps_the_command(self):
        detected, remainder = split_voice_wake_phrase(
            "Pipa, ¿me escuchas? Abre la calculadora.",
            "Pipa me escuchas",
        )

        self.assertTrue(detected)
        self.assertEqual(remainder, "abre la calculadora")
        self.assertEqual(split_voice_wake_phrase("Pipa, ¿me escuchas?", "Pipa me escuchas"), (True, ""))
        self.assertFalse(split_voice_wake_phrase("abre la calculadora", "Pipa me escuchas")[0])

    def test_suspend_command_accepts_natural_windows_phrases(self):
        for phrase in ("suspende el ordenador", "pon el PC en suspensión"):
            with self.subTest(phrase=phrase):
                self.assert_intent(phrase, "system_sleep", {})

    def test_web_search_is_bounded_to_a_query(self):
        self.assert_intent(
            "búscame en internet documentación de Pipa",
            "web_search",
            {"query": "documentación de Pipa"},
        )
        self.assert_intent(
            "busca documentación de Pipa en internet",
            "web_search",
            {"query": "documentación de Pipa"},
        )

    def test_music_requests_strip_natural_language_filler(self):
        for phrase in (
            "pon una canción de Daft Punk en Apple Music",
            "reproduce el tema de Queen en Apple Music",
            "busca canción Blinding Lights en Apple Music",
            "busca Daft Punk en Apple Music",
            "pon la canción Bohemian Rhapsody",
            "reproduce el tema de Queen",
        ):
            with self.subTest(phrase=phrase):
                expected_tool = "music_search"
                intent = parse_text_intent(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.tool_name, expected_tool)
                self.assertEqual(
                    intent.arguments["term"],
                    {
                        "pon una canción de Daft Punk en Apple Music": "Daft Punk",
                        "reproduce el tema de Queen en Apple Music": "Queen",
                        "busca canción Blinding Lights en Apple Music": "Blinding Lights",
                        "busca Daft Punk en Apple Music": "Daft Punk",
                        "pon la canción Bohemian Rhapsody": "Bohemian Rhapsody",
                        "reproduce el tema de Queen": "Queen",
                    }[phrase],
                )

    def test_selected_track_controls_are_not_mistaken_for_a_new_search(self):
        for phrase in (
            "reproduce la canción seleccionada",
            "pon la canción elegida",
        ):
            with self.subTest(phrase=phrase):
                self.assert_intent(phrase, "media_action", {"action": "play_pause"})

    def test_music_requests_without_a_track_open_the_catalogue(self):
        for phrase in (
            "busca música",
            "busca una canción",
            "busca música en Apple Music",
            "busca una canción en Apple Music",
            "quiero escuchar música",
        ):
            with self.subTest(phrase=phrase):
                self.assert_intent(phrase, "music_open", {})

    def test_whatsapp_and_discord_contact_phrases_keep_manual_boundaries(self):
        self.assert_intent(
            "manda un whatsapp para mamá y dile llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un WhatsApp a mamá: llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "escribe a mamá por WhatsApp: llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "prepara un mensaje de WhatsApp para mamá: llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "abre WhatsApp y escribe a mamá: llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un mensaje a +34 600 123 456 en WhatsApp: llego",
            "whatsapp_compose",
            {"phone": "+34 600 123 456", "message": "llego"},
        )
        self.assert_intent(
            "llama a amigo por Discord",
            "discord_call",
            {"contact": "amigo"},
        )
        self.assert_intent(
            "llama por Discord a amigo",
            "discord_call",
            {"contact": "amigo"},
        )
        self.assert_intent(
            "llama a Discord canal 12345678901234567",
            "discord_call_channel",
            {"channel_id": "12345678901234567"},
        )
        self.assert_intent(
            "llama a Discord servidor 98765432109876543 canal 12345678901234567",
            "discord_call_channel",
            {"guild_id": "98765432109876543", "channel_id": "12345678901234567"},
        )
        self.assert_intent(
            "abre el canal 12345678901234567 en Discord",
            "discord_open",
            {"channel_id": "12345678901234567"},
        )
        self.assert_intent(
            "llama al canal 12345678901234567 en Discord",
            "discord_call_channel",
            {"channel_id": "12345678901234567"},
        )
        self.assert_intent(
            "manda un mensaje a mamá por WhatsApp diciendo llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un mensaje por WhatsApp a mamá diciendo llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un mensaje por WhatsApp a +34 600 123 456 diciendo llego en diez minutos",
            "whatsapp_compose",
            {"phone": "+34 600 123 456", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un mensaje de WhatsApp a mamá diciendo llego en diez minutos",
            "whatsapp_contact",
            {"contact": "mamá", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "manda un mensaje de WhatsApp a +34 600 123 456 diciendo llego en diez minutos",
            "whatsapp_compose",
            {"phone": "+34 600 123 456", "message": "llego en diez minutos"},
        )
        self.assert_intent(
            "inicia una llamada con amigo en Discord",
            "discord_call",
            {"contact": "amigo"},
        )
        self.assert_intent(
            "empieza una llamada por Discord con amigo",
            "discord_call",
            {"contact": "amigo"},
        )
        self.assert_intent(
            "haz una llamada de Discord con amigo",
            "discord_call",
            {"contact": "amigo"},
        )
        self.assert_intent(
            "abre Discord con amigo",
            "discord_contact",
            {"contact": "amigo"},
        )

    def test_league_search_accepts_game_and_queue_context(self):
        self.assert_intent(
            "busca una partida ranked solo en el LoL",
            "league_search",
            {"queue": "ranked_solo"},
        )
        self.assert_intent(
            "ponme en cola aram",
            "league_search",
            {"queue": "aram"},
        )
        self.assert_intent(
            "quiero jugar una partida de ARAM",
            "league_search",
            {"queue": "aram"},
        )
        self.assert_intent(
            "busca una partida de LoL",
            "league_search",
            {"queue": "normal_draft"},
        )
        self.assert_intent(
            "inicia matchmaking en ARAM",
            "league_search",
            {"queue": "aram"},
        )

    def test_league_cancel_accepts_natural_game_context(self):
        for phrase in (
            "cancela la búsqueda del LoL",
            "cancela la búsqueda en el League",
            "cancela la búsqueda de lol",
            "cancela la cola del lol",
            "cancela el matchmaking",
        ):
            with self.subTest(phrase=phrase):
                self.assert_intent(phrase, "league_cancel", {})

    def test_league_wait_accepts_a_bounded_read_only_watch(self):
        self.assert_intent(
            "avísame cuando encuentre una partida",
            "league_wait",
            {"seconds": 120},
        )
        self.assert_intent(
            "espera a que el LoL encuentre una partida durante 45 segundos",
            "league_wait",
            {"seconds": 45},
        )
        self.assertIsNone(parse_text_intent("avísame cuando encuentre una partida durante 301 segundos"))

    def test_voice_variants_keep_the_same_safe_tool_routes(self):
        cases = (
            ("busca algo en internet sobre el tiempo", "web_search", {"query": "el tiempo"}),
            ("busca en Google documentación de Pipa", "web_search", {"query": "documentación de Pipa"}),
            ("pon la de Daft Punk", "music_search", {"term": "Daft Punk"}),
            ("quiero escuchar Daft Punk", "music_search", {"term": "Daft Punk"}),
            ("inicia llamada con amigo en Discord", "discord_call", {"contact": "amigo"}),
            ("llama a amigo en Discord ahora", "discord_call", {"contact": "amigo"}),
            ("estado de la cola", "league_search_status", {}),
        )
        for phrase, tool_name, arguments in cases:
            with self.subTest(phrase=phrase):
                self.assert_intent(phrase, tool_name, arguments)

    def test_dictation_punctuation_and_computer_variants_are_accepted(self):
        for phrase in (
            "Estado del ordenador.",
            "¿Estado del ordenador?",
            "Pipa, estado del ordenador.",
            "estado de mi PC",
            "estado de la computadora",
            "cómo está mi ordenador",
        ):
            with self.subTest(phrase=phrase):
                intent = parse_text_intent(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.tool_name, "system_status")
                self.assertEqual(intent.arguments, {})

    def test_optional_wake_name_also_works_with_catalog_phrases(self):
        commands = [
            {
                "phrase": "abre <nombre>",
                "tool_name": "open_app",
                "parameters": [{"name": "name", "kind": "text", "max_length": 80}],
            }
        ]
        intent = parse_catalog_intent("Pipa, abre calculadora", commands)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool_name, "open_app")
        self.assertEqual(intent.arguments, {"name": "calculadora"})

    def test_catalog_app_argument_discards_terminal_dictation_punctuation(self):
        commands = [
            {
                "phrase": "abre una aplicación configurada <nombre>",
                "tool_name": "open_app",
                "parameters": [{"name": "app", "kind": "app", "max_length": 80}],
            }
        ]

        intent = parse_catalog_intent("abre una aplicación configurada calculadora.", commands)

        self.assertIsNotNone(intent)
        self.assertEqual(intent.arguments, {"app": "calculadora"})

    def test_voice_recovery_accepts_minor_asr_errors_for_read_only_status(self):
        for phrase in (
            "estado del ordenado",
            "dime el estado de ordenador por favor",
            "oye estado del pc gracias",
        ):
            with self.subTest(phrase=phrase):
                intent = parse_voice_intent(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.tool_name, "system_status")
                self.assertEqual(intent.arguments, {})

    def test_voice_requests_accept_polite_fillers_articles_and_dictation_punctuation(self):
        for phrase in (
            "Abre la calculadora.",
            "Abre en la calculadora.",
            "¿Podrías abrirme la calculadora, por favor?",
            "Pipa, quiero que abras la calculadora.",
        ):
            with self.subTest(phrase=phrase):
                intent = parse_voice_intent(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.tool_name, "open_app")
                self.assertEqual(intent.arguments, {"app": "calculadora"})

    def test_voice_recovery_can_match_a_high_confidence_fixed_catalog_phrase(self):
        commands = [
            {
                "phrase": "lista los temporizadores",
                "tool_name": "timer_list",
                "parameters": [],
            }
        ]

        intent = parse_voice_intent("lista los temporizadore", commands)

        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool_name, "timer_list")
        self.assertEqual(intent.arguments, {})

    def test_voice_recovery_does_not_guess_external_or_ambiguous_commands(self):
        self.assertIsNone(parse_voice_intent("apaga el ordenado"))
        self.assertIsNone(parse_voice_intent("haz una transferencia bancaria"))
        self.assertIsNone(parse_text_intent("estado del ordenado"))

    def test_voice_opens_only_an_exactly_configured_app_alias_without_a_verb(self):
        for phrase in ("calculadora", "la calculadora", "bloc de notas"):
            with self.subTest(phrase=phrase):
                intent = parse_voice_intent(
                    phrase,
                    [{"tool_name": "open_app"}],
                    direct_app_aliases=("calculadora", "bloc de notas"),
                )
                self.assertIsNotNone(intent)
                self.assertEqual(intent.tool_name, "open_app")
                self.assertIn(intent.arguments["app"], {"calculadora", "bloc de notas"})

        self.assertIsNone(
            parse_voice_intent(
                "haz una transferencia bancaria",
                [{"tool_name": "open_app"}],
                direct_app_aliases=("calculadora",),
            )
        )

    def test_media_controls_do_not_select_or_send_external_content(self):
        self.assert_intent(
            "reproduce la canción seleccionada",
            "media_action",
            {"action": "play_pause"},
        )

    def test_integration_intents_match_the_real_tool_argument_contracts(self):
        catalog = build_agent_catalog(TimerManager())
        examples = (
            ("búscame en internet documentación de Pipa", "web_search"),
            ("busca Daft Punk en Apple Music", "music_search"),
            ("prepara WhatsApp para +34 600 123 456 y dile hola", "whatsapp_compose"),
            ("abre el WhatsApp para +34 600 123 456", "whatsapp_phone_open"),
            ("abre el canal 12345678901234567 en Discord", "discord_open"),
            ("llama al canal 12345678901234567 en Discord", "discord_call_channel"),
            ("quiero jugar una partida de ARAM", "league_search"),
        )
        for phrase, expected_tool in examples:
            with self.subTest(phrase=phrase):
                intent = parse_text_intent(phrase)
                self.assertIsNotNone(intent)
                assert intent is not None
                self.assertEqual(intent.tool_name, expected_tool)
                self.assertEqual(
                    catalog.get(intent.tool_name).validate_arguments(intent.arguments),
                    intent.arguments,
                )


if __name__ == "__main__":
    unittest.main()
