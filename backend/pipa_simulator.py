"""Run a safe protocol smoke test without Waveshare hardware."""

from __future__ import annotations

import json

from pipa_core.simulator import create_simulator
from pipa_core.tools import ToolCatalog, ToolDefinition


def main() -> None:
    simulator = create_simulator(
        ToolCatalog([ToolDefinition("echo", lambda arguments: {"echo": arguments.get("text", "")})])
    )
    outputs = simulator.send("tool_call", name="echo", arguments={"text": "Pipα conectado"})
    for output in outputs:
        print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
