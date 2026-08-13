import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

from backend.pipa_core.simulator import create_simulator  # noqa: E402
from backend.pipa_core.tools import ToolCatalog, ToolDefinition  # noqa: E402


class DeviceSimulatorTests(unittest.TestCase):
    def test_simulator_authenticates_through_the_wire_lifecycle(self):
        simulator = create_simulator(ToolCatalog([]), capabilities=("display", "touch"))

        self.assertIsNotNone(simulator.connection.session_id)
        self.assertEqual(simulator.core.sessions.count(), 1)
        simulator.close()
        self.assertEqual(simulator.core.sessions.count(), 0)

    def test_simulator_can_exercise_physical_confirmation_without_side_effects(self):
        executed = []

        simulator = create_simulator(
            ToolCatalog(
                [
                    ToolDefinition(
                        "external_action",
                        lambda arguments: executed.append(arguments) or {"success": True},
                        safety="unsafe",
                        confirm_summary=lambda _arguments: "Acción externa simulada",
                    )
                ]
            ),
            capabilities=("display", "touch"),
        )

        pending = simulator.send("tool_call", name="external_action", arguments={"value": 1})

        request = next(item for item in pending if item["type"] == "confirm_request")
        self.assertEqual(executed, [])

        completed = simulator.send(
            "confirm",
            confirmation_id=request["confirmation_id"],
            accepted=True,
        )

        self.assertEqual(executed, [{"value": 1}])
        result = next(item for item in completed if item["type"] == "tool_result")
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
