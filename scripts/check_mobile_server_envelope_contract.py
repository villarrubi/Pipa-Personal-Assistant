"""Check that the Swift mobile response envelope matches the Core contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SWIFT_TCP_CLIENT = REPO_ROOT / "mobile-ios" / "Sources" / "PipaMobileCore" / "PipaMobileTCPClient.swift"
_ENTRY = re.compile(
    r'^\s*"(?P<name>[A-Za-z0-9_-]+)"\s*:\s*\[(?P<body>.*?)\],?\s*$',
    re.MULTILINE | re.DOTALL,
)
_STRING = re.compile(r'"([A-Za-z0-9_-]+)"')
_COMMON_FIELDS = frozenset({"protocol_version", "type"})


def _read_swift() -> str:
    try:
        return SWIFT_TCP_CLIENT.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("No se pudo leer el cliente TCP Swift.") from error


def _swift_dictionary(source: str, name: str) -> dict[str, set[str]]:
    marker = f"private static let {name}: [String: Set<String>] = ["
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"No se encontró la allowlist Swift {name}.")
    end = source.find("\n    ]", start + len(marker))
    if end < 0:
        raise ValueError(f"La allowlist Swift {name} no está cerrada.")

    body = source[start + len(marker) : end]
    result: dict[str, set[str]] = {}
    for match in _ENTRY.finditer(body):
        entry_name = match.group("name")
        if entry_name in result:
            raise ValueError(f"La allowlist Swift {name} repite {entry_name}.")
        fields = set(_STRING.findall(match.group("body")))
        if not fields:
            raise ValueError(f"La allowlist Swift {name} deja vacío {entry_name}.")
        result[entry_name] = fields
    if not result:
        raise ValueError(f"La allowlist Swift {name} está vacía.")
    return result


def check_contract() -> tuple[set[str], set[str], set[str]]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from backend.pipa_core.protocol import (  # noqa: PLC0415
        MOBILE_SERVER_MESSAGE_TYPES,
        SERVER_MESSAGE_FIELDS,
        SERVER_MESSAGE_REQUIRED_FIELDS,
    )

    swift_allowed = _swift_dictionary(_read_swift(), "serverFieldContract")
    swift_required = _swift_dictionary(_read_swift(), "serverRequiredFields")
    expected_types = set(MOBILE_SERVER_MESSAGE_TYPES)
    actual_types = set(swift_allowed)
    type_mismatch = expected_types ^ actual_types
    field_mismatch: set[str] = set()
    required_mismatch: set[str] = set()
    for message_type in expected_types & actual_types:
        expected_allowed = set(SERVER_MESSAGE_FIELDS[message_type]) | _COMMON_FIELDS
        actual_allowed = swift_allowed[message_type]
        if expected_allowed != actual_allowed:
            field_mismatch.add(message_type)
        expected_required = set(SERVER_MESSAGE_REQUIRED_FIELDS[message_type]) | _COMMON_FIELDS
        actual_required = swift_required.get(message_type, set())
        if expected_required != actual_required:
            required_mismatch.add(message_type)
    return type_mismatch, field_mismatch, required_mismatch


def main() -> int:
    try:
        type_mismatch, field_mismatch, required_mismatch = check_contract()
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from backend.pipa_core.protocol import MOBILE_SERVER_MESSAGE_TYPES  # noqa: PLC0415
    except (ImportError, KeyError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    if type_mismatch:
        print(f"ERROR: tipos de respuesta móvil desincronizados: {', '.join(sorted(type_mismatch))}")
    if field_mismatch:
        print(f"ERROR: campos permitidos desincronizados: {', '.join(sorted(field_mismatch))}")
    if required_mismatch:
        print(f"ERROR: campos requeridos desincronizados: {', '.join(sorted(required_mismatch))}")
    if type_mismatch or field_mismatch or required_mismatch:
        return 1

    print(f"Contrato de sobres móvil OK: {len(MOBILE_SERVER_MESSAGE_TYPES)} respuestas sincronizadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
