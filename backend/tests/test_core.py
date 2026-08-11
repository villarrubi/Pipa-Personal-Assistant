import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from backend.pipa_core.core import PipaCore  # noqa: E402
from backend.pipa_core.confirmations import ConfirmationError  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition, ToolRouter  # noqa: E402
from trusted_unlock_devices import InMemoryDeviceStore, verifier_from_store  # noqa: E402
from trusted_unlock_simulator import InMemoryTrustedDevice  # noqa: E402


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
            ]
        )
        self.core = PipaCore(verifier_from_store(store), ToolRouter(catalog))
        challenge = self.core.create_challenge(device.device_id)
        session = self.core.authenticate(
            device.device_id,
            challenge.challenge_id,
            device.sign(challenge).signature,
        )
        self.session_id = session.session_id

    def _record(self, arguments):
        self.calls.append(arguments)
        return {"success": True}

    def test_safe_tool_runs_immediately(self):
        outputs = self._send("tool_call", name="safe", arguments={"value": "ok"})
        result = next(item for item in outputs if item["type"] == "tool_result")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["echo"], "ok")

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

    def test_text_intent_routes_to_tool(self):
        outputs = self._send("text_input", text="siguiente canción")
        result = next(item for item in outputs if item["type"] == "tool_result")
        self.assertEqual(result["result"]["action"], "next")

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

    def test_memory_is_scoped_to_authenticated_device(self):
        remembered = self._send("tool_call", name="remember_fact", arguments={"fact": "Apple Music"})
        self.assertTrue(any(item["type"] == "tool_result" for item in remembered))
        recalled = self._send("tool_call", name="recall_memory", arguments={})
        result = next(item for item in recalled if item["type"] == "tool_result")
        self.assertEqual(result["result"]["facts"], ["Apple Music"])

    def _send(self, message_type, **fields):
        from backend.pipa_core.protocol import parse_client_message

        return self.core.handle(
            self.session_id,
            parse_client_message({"protocol_version": 1, "type": message_type, **fields}),
        )


if __name__ == "__main__":
    unittest.main()
