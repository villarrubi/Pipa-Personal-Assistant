"""Check that every capability contract layer matches the Swift TCP allowlists."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SWIFT_TCP_CLIENT = REPO_ROOT / "mobile-ios" / "Sources" / "PipaMobileCore" / "PipaMobileTCPClient.swift"
_SWIFT_STRING = re.compile(r'"([A-Za-z0-9_-]+)"')


def _read_swift() -> str:
    try:
        return SWIFT_TCP_CLIENT.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("No se pudo leer el parser TCP Swift.") from error


def _swift_set(source: str, name: str) -> set[str]:
    marker = f"static let {name}: Set<String> = ["
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"No se encontró la allowlist Swift {name}.")
    end = source.find("]", start + len(marker))
    if end < 0:
        raise ValueError(f"La allowlist Swift {name} no está cerrada.")
    values = set(_SWIFT_STRING.findall(source[start + len(marker) : end]))
    if not values:
        raise ValueError(f"La allowlist Swift {name} está vacía.")
    return values


def _python_contract() -> tuple[set[str], set[str], set[str], set[str]]:
    agent_path = str(REPO_ROOT / "windows-agent")
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)

    from tools.integration_catalog import build_integration_capabilities  # noqa: PLC0415

    capabilities = build_integration_capabilities(
        apple_music_configured=True,
        apple_music_launcher_resolved=True,
        league_available=True,
        league_launcher_resolved=True,
        league_ready=True,
        codex_configured=True,
        codex_launcher_resolved=True,
        whatsapp_app_configured=True,
        whatsapp_launcher_resolved=True,
        discord_app_configured=True,
        discord_launcher_resolved=True,
        whatsapp_contacts_configured=True,
        discord_contacts_configured=True,
    )

    groups = set(capabilities)
    boolean_fields: set[str] = set()
    string_fields: set[str] = set()
    list_fields: set[str] = set()
    for fields in capabilities.values():
        for field_name, value in fields.items():
            if type(value) is bool:
                boolean_fields.add(field_name)
            elif isinstance(value, str):
                string_fields.add(field_name)
            elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                list_fields.add(field_name)
            else:
                raise ValueError(f"Tipo de capacidad no soportado: {field_name}.")
    return groups, boolean_fields, string_fields, list_fields


def _core_contract() -> tuple[set[str], set[str], set[str], set[str]]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from backend.pipa_core.capability_contract import (  # noqa: PLC0415
        _CAPABILITY_BOOLEAN_FIELDS,
        _CAPABILITY_GROUPS,
        _CAPABILITY_LIST_FIELDS,
        _CAPABILITY_STRING_FIELDS,
    )

    return (
        set(_CAPABILITY_GROUPS),
        set(_CAPABILITY_BOOLEAN_FIELDS),
        set(_CAPABILITY_STRING_FIELDS),
        set(_CAPABILITY_LIST_FIELDS),
    )


def check_contract() -> tuple[set[str], set[str], set[str], set[str]]:
    python_groups, python_bool, python_string, python_list = _python_contract()
    core_groups, core_bool, core_string, core_list = _core_contract()
    swift = _read_swift()
    swift_groups = _swift_set(swift, "capabilityGroups")
    swift_bool = _swift_set(swift, "booleanCapabilityFields")
    swift_string = _swift_set(swift, "stringCapabilityFields")
    swift_list = _swift_set(swift, "listCapabilityFields")

    contracts = (
        (python_groups, python_bool, python_string, python_list),
        (core_groups, core_bool, core_string, core_list),
        (swift_groups, swift_bool, swift_string, swift_list),
    )
    reference = contracts[0]
    mismatches = [set() for _ in reference]
    for contract in contracts[1:]:
        for index, (expected_values, actual_values) in enumerate(zip(reference, contract, strict=True)):
            mismatches[index].update(expected_values ^ actual_values)

    for contract in contracts:
        _, boolean_fields, string_fields, list_fields = contract
        overlap = (
            (boolean_fields & string_fields) | (boolean_fields & list_fields) | (string_fields & list_fields)
        )
        mismatches[1].update(overlap)
    return mismatches[0], mismatches[1], mismatches[2], mismatches[3]


def main() -> int:
    try:
        mismatches = check_contract()
    except (ImportError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    if any(mismatches):
        labels = ("groups", "booleanos", "textos", "listas")
        for label, values in zip(labels, mismatches, strict=True):
            if values:
                print(
                    f"ERROR: deriva de capacidades Python/Core/Swift en {label}: {', '.join(sorted(values))}"
                )
        return 1

    groups, boolean_fields, string_fields, list_fields = _python_contract()
    print(
        "Contrato de capacidades móvil OK: "
        f"{len(groups)} grupos, {len(boolean_fields)} booleanos, "
        f"{len(string_fields)} textos y {len(list_fields)} listas."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
