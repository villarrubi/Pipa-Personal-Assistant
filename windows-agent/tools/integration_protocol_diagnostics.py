"""In-memory end-to-end checks for the device integration protocol.

The real integration handlers are deliberately replaced with synthetic
handlers. The test still uses the real catalog metadata, argument validators,
Pipa Core, session authentication, confirmation lifecycle and device result
redaction, so it exercises the path a Waveshare device will use without
opening a browser, starting an application, contacting League or touching
persistent keys.
"""

from __future__ import annotations

import json
from typing import Any

from backend.pipa_core.simulator import create_simulator
from backend.pipa_core.tools import ToolCatalog, ToolDefinition
from tools.agent_catalog import build_agent_catalog
from tools.timers import TimerManager

_INTEGRATION_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("web_search", {"query": "Pipa private demo query"}),
    ("music_search", {"term": "Pipa private demo song"}),
    (
        "whatsapp_compose",
        {"phone": "+34600000000", "message": "Pipa private demo message"},
    ),
    ("discord_call_channel", {"channel_id": "12345678901234567"}),
    ("league_search", {"queue": "ranked_solo"}),
)


def _synthetic_catalog(executed: list[str]) -> ToolCatalog:
    """Copy real safety metadata while replacing every outward handler."""

    real_catalog = build_agent_catalog(TimerManager())
    definitions: list[ToolDefinition] = []
    for tool_name, _arguments in _INTEGRATION_CASES:
        real_definition = real_catalog.get(tool_name)

        def simulated_handler(_values: dict[str, Any], *, name: str = tool_name) -> dict[str, Any]:
            executed.append(name)
            return {"success": True, "simulated": True}

        definitions.append(
            ToolDefinition(
                tool_name,
                simulated_handler,
                safety=real_definition.safety,
                confirm_summary=real_definition.confirm_summary,
                argument_validator=real_definition.argument_validator,
            )
        )
    return ToolCatalog(definitions)


def run_integration_protocol_self_test() -> dict[str, object]:
    """Exercise five real tool contracts through an authenticated simulator."""

    executed: list[str] = []
    simulator = create_simulator(
        _synthetic_catalog(executed),
        capabilities=("display", "touch"),
    )
    try:
        for index, (tool_name, arguments) in enumerate(_INTEGRATION_CASES):
            executed_before = len(executed)
            pending = simulator.send(
                "tool_call",
                name=tool_name,
                arguments=arguments,
                call_id=f"integration-demo-{index}",
            )
            confirmation = next(
                (item for item in pending if item.get("type") == "confirm_request"),
                None,
            )
            if confirmation is None or len(executed) != executed_before:
                raise ValueError(f"{tool_name} did not stop at confirmation")

            pending_text = json.dumps(pending, ensure_ascii=False)
            if any(str(value) in pending_text for value in arguments.values()):
                raise ValueError(f"{tool_name} leaked arguments before confirmation")

            completed = simulator.send(
                "confirm",
                confirmation_id=confirmation["confirmation_id"],
                accepted=True,
            )
            result = next(
                (item for item in completed if item.get("type") == "tool_result"),
                None,
            )
            if not isinstance(result, dict) or result.get("success") is not True:
                raise ValueError(f"{tool_name} did not complete after confirmation")
            completed_text = json.dumps(completed, ensure_ascii=False)
            if any(str(value) in completed_text for value in arguments.values()):
                raise ValueError(f"{tool_name} leaked arguments after confirmation")

        expected_tools = [name for name, _arguments in _INTEGRATION_CASES]
        if executed != expected_tools:
            raise ValueError("synthetic handlers did not execute in the expected order")
    finally:
        simulator.close()

    return {
        "commands_checked": len(_INTEGRATION_CASES),
        "confirmation_gated": True,
        "executed_only_after_confirmation": True,
        "result_redacted": True,
        "simulated_handlers_executed": len(executed),
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }
