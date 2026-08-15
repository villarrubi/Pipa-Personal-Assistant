"""Run a safe protocol smoke test without Waveshare hardware."""

from __future__ import annotations

import json

from pipa_core.simulator import create_simulator
from pipa_core.tools import ToolCatalog, ToolDefinition


def main() -> None:
    executed = []

    def simulated_external_action(arguments):
        executed.append(dict(arguments))
        return {"success": True, "simulated": True}

    simulator = create_simulator(
        ToolCatalog(
            [
                ToolDefinition("echo", lambda arguments: {"echo": arguments.get("text", "")}),
                ToolDefinition(
                    "simulated_external_action",
                    simulated_external_action,
                    safety="unsafe",
                    confirm_summary=lambda _arguments: "Ejecutar acción simulada",
                ),
            ]
        ),
        capabilities=("display", "touch"),
    )
    outputs = simulator.send("tool_call", name="echo", arguments={"text": "Pipα conectado"})
    for output in outputs:
        print(json.dumps(output, ensure_ascii=True))

    pending = simulator.send(
        "tool_call",
        name="simulated_external_action",
        arguments={"source": "smoke-test"},
    )
    for output in pending:
        print(json.dumps(output, ensure_ascii=True))
    confirmation = next(item for item in pending if item["type"] == "confirm_request")
    completed = simulator.send(
        "confirm",
        confirmation_id=confirmation["confirmation_id"],
        accepted=True,
    )
    for output in completed:
        print(json.dumps(output, ensure_ascii=True))
    if executed != [{"source": "smoke-test"}]:
        raise RuntimeError("simulator smoke test executed unexpected arguments")


if __name__ == "__main__":
    main()
