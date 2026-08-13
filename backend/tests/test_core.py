import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402

from backend.pipa_core.confirmations import (
    MAX_PENDING_CONFIRMATIONS,
    MAX_PENDING_PER_OWNER,
    ConfirmationError,
    ConfirmationManager,
)  # noqa: E402
from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        device = InMemoryTrustedDevice.generate("test-device")
        store = InMemoryDeviceStore()
        store.register(device.device_id, device.public_key)
        self.device = device
        catalog = ToolCatalog(
            [
                ToolDefinition("safe", lambda args: {"echo": args["value"]}),
                ToolDefinition("media_action", lambda args: {"action": args["action"]}),
                ToolDefinition(
                    "unsafe",
                    lambda args: self._record(args),
                    safety="unsafe",
                    confirm_summary=lambda args: f"Ejecutar {args['value']}",
                ),
                ToolDefinition(
                    "failing_unsafe",
                    lambda _args: self._fail_after_confirmation(),
                    safety="unsafe",
                    confirm_summary=lambda _args: "Ejecutar adaptador inestable",
                ),
            ]
        )
        self.core = PipaCore(
            verifier_from_store(store),
            ToolRouter(catalog),
            command_catalog=lambda: [
                {
                    "id": "safe",
                    "tool_name": "safe",
                    "phrase": "prueba segura",
                    "description": "Una prueba segura.",
                    "safety": "safe",
                    "requires_confirmation": False,
                }
            ],
        )
        challenge = self.core.create_challenge(device.device_id)
        session = self.core.authenticate(
            device.device_id,
            challenge.challenge_id,
            device.sign(challenge).signature,
            capabilities=["display", "touch"],
        )
        self.session_id = session.session_id

    def _record(self, arguments):
        self.calls.append(arguments)
        return {"success": True}

    @staticmethod
    def _fail_after_confirmation():
        raise RuntimeError("private-token-must-not-cross-device")

    def test_safe_result_captions_expose_only_allowlisted_coarse_status(self):
        cases = (
            (
                "system_power",
                {"success": True, "available": True, "percent": 72, "plugged": False},
                "Batería: 72%; sin corriente.",
            ),
            (
                "system_network",
                {"success": True, "interfaces": {"Wi-Fi privada": {"is_up": True}}},
                "Estado de red consultado.",
            ),
            (
                "integration_status",
                {"success": True, "whatsapp": {"contact_aliases_configured": False}},
                "Estado de integraciones consultado.",
            ),
            (
                "league_search_status",
                {"success": True, "supported": True, "searching": True, "state": "searching"},
                "League está buscando partida.",
            ),
            (
                "league_search_status",
                {"success": True, "supported": True, "searching": False, "state": "unknown"},
                "No se pudo confirmar el estado de búsqueda de League.",
            ),
            (
                "timer_list",
                {"success": True, "timers": [{"timer_id": "private-id", "label": "private label"}]},
                "Temporizadores registrados: 1.",
            ),
        )

        for tool_name, result, expected in cases:
            with self.subTest(tool_name=tool_name):
                caption = self.core._safe_result_caption(tool_name, result)
                self.assertEqual(caption, expected)
                self.assertNotIn("private", caption.lower())

    def test_safe_tool_runs_immediately(self):
        outputs = self._send("tool_call", name="safe", arguments={"value": "ok"})
        result = next(item for item in outputs if item["type"] == "tool_result")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["success"])
        self.assertNotIn("result", result)

    def test_device_tool_result_does_not_leak_handler_data(self):
        outputs = self._send("tool_call", name="safe", arguments={"value": "private-value"})
        result = next(item for item in outputs if item["type"] == "tool_result")

        self.assertNotIn("private-value", str(result))
        self.assertNotIn("result", result)

    def test_unsafe_tool_waits_for_confirmation(self):
        outputs = self._send("tool_call", name="unsafe", arguments={"value": "llamar"})
        request = next(item for item in outputs if item["type"] == "confirm_request")
        self.assertEqual(self.calls, [])

        outputs = self._send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )
        self.assertEqual(self.calls, [{"value": "llamar"}])
        self.assertTrue(any(item["type"] == "tool_result" for item in outputs))
        ui = next(item for item in outputs if item["type"] == "ui_state")
        self.assertEqual(ui["caption"], "Acción completada.")

    def test_device_confirmation_does_not_echo_tool_arguments(self):
        outputs = self._send(
            "tool_call",
            name="unsafe",
            arguments={"value": "private-phone https://private.example mensaje secreto"},
        )

        request = next(item for item in outputs if item["type"] == "confirm_request")
        self.assertEqual(request["summary"], "Confirmar acción externa.")
        self.assertNotIn("private-phone", str(request))
        self.assertNotIn("private.example", str(request))
        self.assertNotIn("mensaje secreto", str(request))

    def test_call_id_survives_confirmation_without_exposing_handler_data(self):
        outputs = self._send(
            "tool_call",
            name="unsafe",
            arguments={"value": "call-correlated"},
            call_id="request-42",
        )
        request = next(item for item in outputs if item["type"] == "confirm_request")
        self.assertEqual(request["call_id"], "request-42")

        outputs = self._send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )
        result = next(item for item in outputs if item["type"] == "tool_result")
        self.assertEqual(result["call_id"], "request-42")
        self.assertNotIn("result", result)

    def test_confirmed_tool_failure_is_generic_and_keeps_session_alive(self):
        outputs = self._send("tool_call", name="failing_unsafe", arguments={})
        request = next(item for item in outputs if item["type"] == "confirm_request")

        outputs = self._send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )

        self.assertEqual(outputs[0]["type"], "error")
        self.assertEqual(outputs[0]["code"], "tool_failed")
        self.assertNotIn("private-token", str(outputs))
        self.assertEqual(outputs[1]["type"], "ui_state")
        self.assertEqual(outputs[1]["state"], "idle")

        retry = self._send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )
        self.assertEqual(retry[0]["code"], "confirmation_failed")
        self.assertEqual(retry[0]["message"], "La confirmación ha caducado o no es válida.")

    def test_text_intent_routes_to_tool(self):
        outputs = self._send("text_input", text="siguiente canción")
        result = next(item for item in outputs if item["type"] == "tool_result")
        self.assertTrue(result["success"])
        self.assertNotIn("result", result)

    def test_catalog_request_returns_only_bounded_ui_metadata(self):
        outputs = self._send("catalog_request")

        self.assertEqual(outputs[0]["type"], "catalog")
        self.assertEqual(outputs[0]["commands"][0]["tool_name"], "safe")
        self.assertEqual(
            set(outputs[0]["commands"][0]),
            {"id", "tool_name", "phrase", "description", "safety", "requires_confirmation"},
        )

    def test_catalog_request_preserves_bounded_structured_parameters(self):
        self.core.command_catalog = lambda: [
            {
                "id": "whatsapp_compose",
                "tool_name": "safe",
                "phrase": "prepara WhatsApp",
                "description": "Prepara un chat.",
                "safety": "safe",
                "requires_confirmation": False,
                "parameters": [
                    {"name": "message", "label": "Mensaje", "kind": "message", "max_length": 3800},
                    {
                        "name": "queue",
                        "label": "Cola",
                        "kind": "queue",
                        "max_length": 32,
                        "options": ["aram", "normal_draft"],
                    },
                ],
            }
        ]

        outputs = self._send("catalog_request")

        self.assertEqual(
            outputs[0]["commands"][0]["parameters"],
            [
                {"name": "message", "label": "Mensaje", "kind": "message", "max_length": 3800},
                {
                    "name": "queue",
                    "label": "Cola",
                    "kind": "queue",
                    "max_length": 32,
                    "options": ["aram", "normal_draft"],
                },
            ],
        )

    def test_catalog_request_preserves_bounded_fixed_arguments(self):
        self.core.command_catalog = lambda: [
            {
                "id": "media_play_pause",
                "tool_name": "media_action",
                "phrase": "reproduce la canción seleccionada",
                "description": "Controla el reproductor activo.",
                "safety": "safe",
                "requires_confirmation": False,
                "parameters": [],
                "default_arguments": {"action": "play_pause"},
            }
        ]

        outputs = self._send("catalog_request")

        self.assertEqual(
            outputs[0]["commands"][0]["default_arguments"],
            {"action": "play_pause"},
        )

    def test_catalog_rejects_fixed_arguments_with_controls_or_editable_parameters(self):
        self.core.command_catalog = lambda: [
            {
                "id": "bad-fixed-arguments",
                "tool_name": "media_action",
                "phrase": "reproduce",
                "description": "Controla.",
                "safety": "safe",
                "requires_confirmation": False,
                "parameters": [{"name": "action", "label": "Acción", "kind": "action", "max_length": 16}],
                "default_arguments": {"action": "play_pause\u202e"},
            }
        ]

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])

    def test_catalog_rejects_untrusted_parameter_metadata(self):
        self.core.command_catalog = lambda: [
            {
                "id": "unsafe-parameter",
                "tool_name": "safe",
                "phrase": "prueba",
                "description": "Prueba.",
                "safety": "safe",
                "requires_confirmation": False,
                "parameters": [
                    {
                        "name": "query",
                        "label": "Consulta",
                        "kind": "text",
                        "max_length": 200,
                        "private": "no debe cruzar",
                    }
                ],
            }
        ]

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])
        self.assertNotIn("no debe cruzar", str(outputs))

    def test_catalog_provider_failure_is_generic_and_fails_closed(self):
        self.core.command_catalog = lambda: [{"id": "bad", "private": "should-not-cross"}]

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])
        self.assertNotIn("should-not-cross", str(outputs))

    def test_catalog_can_include_a_bounded_public_capability_matrix(self):
        self.core.capability_catalog = lambda: {
            "apple_music": {
                "available": True,
                "playback": False,
                "requires_manual_selection": True,
            },
            "league": {"available": False, "queues": ["aram", "normal_draft"]},
        }

        outputs = self._send("catalog_request")

        self.assertEqual(
            outputs[0]["capabilities"],
            {
                "apple_music": {
                    "available": True,
                    "playback": False,
                    "requires_manual_selection": True,
                },
                "league": {"available": False, "queues": ["aram", "normal_draft"]},
            },
        )

    def test_catalog_rejects_unbounded_or_nested_capability_data(self):
        self.core.capability_catalog = lambda: {"unsafe": {"private": {"token": "must-not-cross"}}}

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])

    def test_catalog_rejects_unknown_capability_fields(self):
        self.core.capability_catalog = lambda: {"apple_music": {"private_path": "C:\\Users"}}

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])

    def test_catalog_rejects_control_characters_in_capability_text(self):
        self.core.capability_catalog = lambda: {
            "apple_music": {"execution": "opens_browser\nprivate"},
        }

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])

    def test_catalog_safety_metadata_must_match_registered_tool(self):
        self.core.command_catalog = lambda: [
            {
                "id": "unsafe",
                "tool_name": "unsafe",
                "phrase": "acción externa",
                "description": "Acción externa.",
                "safety": "safe",
                "requires_confirmation": False,
            }
        ]

        outputs = self._send("catalog_request")

        self.assertEqual(outputs, [{"protocol_version": 1, "type": "error", "code": "catalog_unavailable"}])

    def test_audio_end_fails_closed_instead_of_leaving_thinking_state(self):
        for message_type in ("hold_end", "audio_end"):
            with self.subTest(message_type=message_type):
                self._send("wake")
                outputs = self._send(message_type)

                self.assertEqual(outputs[0]["type"], "error")
                self.assertEqual(outputs[0]["code"], "voice_unavailable")
                self.assertNotIn("audio", str(outputs[0]))
                self.assertEqual(outputs[1]["type"], "ui_state")
                self.assertEqual(outputs[1]["state"], "idle")
                self.assertEqual(outputs[1]["caption"], "La voz aún no está disponible.")

    def test_confirmation_is_bound_to_session(self):
        outputs = self._send("tool_call", name="unsafe", arguments={"value": "privado"})
        request = next(item for item in outputs if item["type"] == "confirm_request")
        with self.assertRaises(ConfirmationError):
            self.core.router.resolve_confirmation(
                request["confirmation_id"],
                True,
                owner_id="another-session",
            )
        self.assertEqual(self.calls, [])

    def test_abort_invalidates_pending_action(self):
        outputs = self._send("tool_call", name="unsafe", arguments={"value": "cancelar"})
        request = next(item for item in outputs if item["type"] == "confirm_request")

        aborted = self._send("abort")
        self.assertEqual(aborted[0]["type"], "tts_aborted")

        outputs = self._send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )
        self.assertEqual(outputs[0]["code"], "confirmation_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(outputs[1]["state"], "idle")

    def test_new_tool_call_is_rejected_while_confirmation_is_visible(self):
        outputs = self._send("tool_call", name="unsafe", arguments={"value": "primera"})
        request = next(item for item in outputs if item["type"] == "confirm_request")

        outputs = self._send("tool_call", name="unsafe", arguments={"value": "segunda"})

        self.assertEqual(outputs[0]["code"], "confirmation_required")
        self.assertEqual(self.calls, [])
        self.assertEqual(outputs[1]["state"], "confirm")

        self._send("confirm", confirmation_id=request["confirmation_id"], accepted=False)

    def test_wake_cannot_bypass_visible_confirmation(self):
        outputs = self._send("tool_call", name="unsafe", arguments={"value": "primera"})
        request = next(item for item in outputs if item["type"] == "confirm_request")

        outputs = self._send("wake")

        self.assertEqual(outputs[0]["code"], "confirmation_required")
        self.assertEqual(outputs[1]["state"], "confirm")
        self.assertEqual(self.calls, [])
        self._send("confirm", confirmation_id=request["confirmation_id"], accepted=False)

    def test_unsafe_tool_is_rejected_without_physical_confirmation_capabilities(self):
        device = InMemoryTrustedDevice.generate("no-screen")
        store = InMemoryDeviceStore()
        store.register(device.device_id, device.public_key)
        core = PipaCore(
            verifier_from_store(store),
            ToolRouter(
                ToolCatalog(
                    [
                        ToolDefinition(
                            "unsafe",
                            lambda _args: {"success": True},
                            safety="unsafe",
                            confirm_summary=lambda _args: "Acción externa",
                        )
                    ]
                )
            ),
        )
        challenge = core.create_challenge(device.device_id)
        session = core.authenticate(
            device.device_id,
            challenge.challenge_id,
            device.sign(challenge).signature,
            capabilities=["usb_serial"],
        )

        outputs = core.handle(
            session.session_id,
            self._message("tool_call", name="unsafe", arguments={}),
        )

        self.assertEqual(outputs[0]["code"], "confirmation_unavailable")
        self.assertEqual(outputs[1]["state"], "idle")

    def test_secure_session_requires_one_device_metadata_announcement(self):
        session = self.core.sessions.create(
            self.device.device_id,
            capabilities_initialized=False,
        )

        before_hello = self.core.handle(
            session.session_id,
            self._message("tool_call", name="unsafe", arguments={"value": "prematuro"}),
        )
        self.assertEqual(before_hello[0]["code"], "device_hello_required")
        self.assertNotIn("confirm_request", {item["type"] for item in before_hello})

        catalog_before_hello = self.core.handle(session.session_id, self._message("catalog_request"))
        self.assertEqual(catalog_before_hello[0]["code"], "device_hello_required")

        outputs = self.core.handle(
            session.session_id,
            self._message(
                "device_hello",
                firmware_version="0.2.0",
                capabilities=["display", "touch"],
            ),
        )

        self.assertEqual(outputs[0]["type"], "device_hello_ack")
        self.assertEqual(session.firmware_version, "0.2.0")
        self.assertEqual(session.capabilities, ("display", "touch"))
        self.assertTrue(session.capabilities_initialized)

        repeated = self.core.handle(
            session.session_id,
            self._message(
                "device_hello",
                firmware_version="0.2.1",
                capabilities=["display", "touch"],
            ),
        )
        self.assertEqual(repeated[0]["code"], "device_hello_not_expected")
        self.assertEqual(session.firmware_version, "0.2.0")

    @staticmethod
    def _message(message_type, **fields):
        from backend.pipa_core.protocol import parse_client_message

        return parse_client_message({"protocol_version": 1, "type": message_type, **fields})

    def test_confirmation_expires_at_the_boundary(self):
        manager = ConfirmationManager(ttl_seconds=30)
        with patch("backend.pipa_core.confirmations.time.time", return_value=100):
            pending = manager.create("unsafe", {"value": "x"}, "Ejecutar x")

        with self.assertRaises(ConfirmationError):
            manager.consume(pending.confirmation_id, now=130)

    def test_confirmation_manager_rejects_empty_summary_and_has_a_pending_cap(self):
        manager = ConfirmationManager()
        with self.assertRaises(ConfirmationError):
            manager.create("unsafe", {}, "")

        for index in range(MAX_PENDING_CONFIRMATIONS):
            manager.create("unsafe", {"index": index}, "Acción segura")
        with self.assertRaises(ConfirmationError):
            manager.create("unsafe", {}, "Otra acción")

    def test_confirmation_manager_limits_each_owner(self):
        manager = ConfirmationManager()
        for index in range(MAX_PENDING_PER_OWNER):
            manager.create("unsafe", {"index": index}, "Acción segura", owner_id="device-a")
        with self.assertRaises(ConfirmationError):
            manager.create("unsafe", {}, "Otra acción", owner_id="device-a")
        manager.create("unsafe", {}, "Acción de otro dispositivo", owner_id="device-b")

    def test_memory_is_scoped_to_authenticated_device(self):
        remembered = self._send("tool_call", name="remember_fact", arguments={"fact": "Apple Music"})
        self.assertTrue(any(item["type"] == "tool_result" for item in remembered))
        recalled = self._send("tool_call", name="recall_memory", arguments={})
        result = next(item for item in recalled if item["type"] == "tool_result")
        self.assertTrue(result["success"])
        self.assertNotIn("Apple Music", str(result))

    def test_ping_and_status_refresh_session(self):
        pong = self._send("ping", request_id="heartbeat-1")
        self.assertEqual(pong[0]["type"], "pong")
        self.assertEqual(pong[0]["request_id"], "heartbeat-1")

        acknowledged = self._send(
            "device_status", audio_state="probe_only", battery_percent=75, wifi_rssi=-60
        )
        self.assertEqual(acknowledged[0]["type"], "status_ack")
        session = self.core.sessions.get(self.session_id)
        self.assertEqual(session.audio_state, "probe_only")
        self.assertEqual(session.battery_percent, 75)
        self.assertEqual(session.wifi_rssi, -60)

    def test_memory_has_a_global_device_bound(self):
        from backend.pipa_core.memory import MAX_MEMORY_DEVICES, MemoryStore

        memory = MemoryStore()
        for index in range(MAX_MEMORY_DEVICES):
            memory.remember(f"device-{index}", "fact")

        with self.assertRaises(ValueError):
            memory.remember("one-too-many", "fact")

    def _send(self, message_type, **fields):
        from backend.pipa_core.protocol import parse_client_message

        return self.core.handle(
            self.session_id,
            parse_client_message({"protocol_version": 1, "type": message_type, **fields}),
        )


if __name__ == "__main__":
    unittest.main()
