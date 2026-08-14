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
    ("open_app", {"app": "calculadora"}),
    ("open_codex", {}),
    ("web_search", {"query": "Pipa private demo query"}),
    ("music_open", {}),
    ("music_search", {"term": "Pipa private demo song"}),
    ("whatsapp_open", {}),
    (
        "whatsapp_compose",
        {"phone": "+34600000000", "message": "Pipa private demo message"},
    ),
    ("whatsapp_contact", {"contact": "demo alias", "message": "Pipa private demo message"}),
    ("whatsapp_contact_open", {"contact": "demo alias"}),
    ("whatsapp_phone_open", {"phone": "+34600000000"}),
    ("discord_open_app", {}),
    (
        "discord_open",
        {"channel_id": "12345678901234567", "guild_id": "98765432109876543"},
    ),
    ("discord_contact", {"contact": "demo alias"}),
    (
        "discord_call_channel",
        {"channel_id": "12345678901234567", "guild_id": "98765432109876543"},
    ),
    ("discord_call", {"contact": "demo alias"}),
    ("league_open", {}),
    ("league_search", {"queue": "ranked_solo"}),
    ("league_cancel", {}),
)
INTEGRATION_CASE_COUNT = len(_INTEGRATION_CASES)

# Read-only integration status calls do not need a touch confirmation, but
# they still belong in the protocol smoke test. Keeping them in a separate
# matrix makes the distinction explicit and prevents a future status route
# from accidentally inheriting the outward-action test's assumptions.
_READ_ONLY_INTEGRATION_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("integration_status", {}),
    ("league_status", {}),
    ("league_search_status", {}),
)
READ_ONLY_INTEGRATION_CASE_COUNT = len(_READ_ONLY_INTEGRATION_CASES)

# These phrases use the same parser path as a future voice-capable device.
# Keep destinations synthetic and direct so the diagnostic never needs local
# contact aliases or a real application while still exercising every named
# integration from natural language through confirmation.
_VOICE_INTEGRATION_CASES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "busca en internet Pipa private demo query",
        "web_search",
        {"query": "Pipa private demo query"},
    ),
    (
        "pon una canción de Daft Punk en Apple Music",
        "music_search",
        {"term": "Daft Punk"},
    ),
    (
        "prepara WhatsApp para +34 600 000 000 y dile Pipa private demo message",
        "whatsapp_compose",
        {"phone": "+34 600 000 000", "message": "Pipa private demo message"},
    ),
    (
        "llama a Discord canal 12345678901234567",
        "discord_call_channel",
        {"channel_id": "12345678901234567"},
    ),
    (
        "busca partida en el LoL",
        "league_search",
        {"queue": "normal_draft"},
    ),
)
VOICE_INTEGRATION_CASE_COUNT = len(_VOICE_INTEGRATION_CASES)


def _synthetic_catalog(executed: list[str]) -> ToolCatalog:
    """Copy real safety metadata while replacing every outward handler."""

    real_catalog = build_agent_catalog(TimerManager())
    definitions: list[ToolDefinition] = []
    for tool_name, _arguments in (*_INTEGRATION_CASES, *_READ_ONLY_INTEGRATION_CASES):
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


def _check_read_only_cases(simulator, executed: list[str]) -> None:
    """Verify that status routes execute directly and never request touch."""

    for tool_name, arguments in _READ_ONLY_INTEGRATION_CASES:
        executed_before = len(executed)
        responses = simulator.send(
            "tool_call",
            name=tool_name,
            arguments=arguments,
        )
        if any(item.get("type") == "confirm_request" for item in responses):
            raise ValueError(f"read-only route unexpectedly requested confirmation: {tool_name}")
        result = next((item for item in responses if item.get("type") == "tool_result"), None)
        if (
            not isinstance(result, dict)
            or result.get("tool_name") != tool_name
            or result.get("success") is not True
            or len(executed) != executed_before + 1
        ):
            raise ValueError(f"read-only route did not execute safely: {tool_name}")


def _check_voice_cases(simulator, executed: list[str]) -> None:
    """Route natural-language cases through the real Core parser safely."""

    for _index, (phrase, expected_tool, arguments) in enumerate(_VOICE_INTEGRATION_CASES):
        executed_before = len(executed)
        pending = simulator.send(
            "text_input",
            text=phrase,
            source="voice",
        )
        confirmation = next(
            (item for item in pending if item.get("type") == "confirm_request"),
            None,
        )
        if (
            confirmation is None
            or confirmation.get("tool_name") != expected_tool
            or len(executed) != executed_before
        ):
            raise ValueError(f"voice route did not stop at confirmation: {expected_tool}")

        pending_text = json.dumps(pending, ensure_ascii=False)
        if any(str(value) in pending_text for value in arguments.values()):
            raise ValueError(f"voice route leaked arguments before confirmation: {expected_tool}")

        completed = simulator.send(
            "confirm",
            confirmation_id=confirmation["confirmation_id"],
            accepted=True,
        )
        result = next(
            (item for item in completed if item.get("type") == "tool_result"),
            None,
        )
        if (
            not isinstance(result, dict)
            or result.get("tool_name") != expected_tool
            or result.get("success") is not True
        ):
            raise ValueError(f"voice route did not complete after confirmation: {expected_tool}")
        completed_text = json.dumps(completed, ensure_ascii=False)
        if any(str(value) in completed_text for value in arguments.values()):
            raise ValueError(f"voice route leaked arguments after confirmation: {expected_tool}")


def run_integration_protocol_self_test() -> dict[str, object]:
    """Exercise every outward integration tool through an authenticated simulator."""

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

        _check_voice_cases(simulator, executed)
        _check_read_only_cases(simulator, executed)

        expected_tools = [name for name, _arguments in _INTEGRATION_CASES]
        expected_tools.extend(tool_name for _phrase, tool_name, _arguments in _VOICE_INTEGRATION_CASES)
        expected_tools.extend(name for name, _arguments in _READ_ONLY_INTEGRATION_CASES)
        if executed != expected_tools:
            raise ValueError("synthetic handlers did not execute in the expected order")
    finally:
        simulator.close()

    return {
        "commands_checked": INTEGRATION_CASE_COUNT,
        "voice_commands_checked": VOICE_INTEGRATION_CASE_COUNT,
        "read_only_commands_checked": READ_ONLY_INTEGRATION_CASE_COUNT,
        "confirmation_gated": True,
        "executed_only_after_confirmation": True,
        "result_redacted": True,
        "simulated_handlers_executed": len(executed),
        "external_actions_executed": False,
        "persistent_keys_touched": False,
    }
