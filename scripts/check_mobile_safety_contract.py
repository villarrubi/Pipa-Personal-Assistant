"""Check that mobile safety boundaries match the Python integration contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SWIFT_VIEW_MODEL = REPO_ROOT / "mobile-ios" / "Sources" / "PipaMobileUI" / "PipaMobileViewModel.swift"
_ENTRY = re.compile(
    r'^\s*"(?P<group>[A-Za-z0-9_-]+)"\s*:\s*\[(?P<body>[^\]]*)\],?\s*$',
    re.MULTILINE,
)
_FIELD = re.compile(r'"(?P<field>[A-Za-z0-9_-]+)"\s*:\s*(?P<value>true|false)')


def _read_swift() -> str:
    try:
        return SWIFT_VIEW_MODEL.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("No se pudo leer el modelo Swift de capacidades.") from error


def _swift_contract(source: str) -> dict[str, dict[str, bool]]:
    marker = "private static let safetyContract: [String: [String: Bool]] = ["
    start = source.find(marker)
    if start < 0:
        raise ValueError("No se encontró el contrato Swift de seguridad móvil.")
    end = source.find("\n    ]", start + len(marker))
    if end < 0:
        raise ValueError("El contrato Swift de seguridad móvil no está cerrado.")

    result: dict[str, dict[str, bool]] = {}
    body = source[start + len(marker) : end]
    for match in _ENTRY.finditer(body):
        group = match.group("group")
        fields = {
            field.group("field"): field.group("value") == "true"
            for field in _FIELD.finditer(match.group("body"))
        }
        if not fields or group in result:
            raise ValueError("El contrato Swift de seguridad móvil contiene una entrada inválida.")
        result[group] = fields
    if not result:
        raise ValueError("El contrato Swift de seguridad móvil está vacío.")
    return result


def _python_contract() -> dict[str, dict[str, bool]]:
    agent_path = str(REPO_ROOT / "windows-agent")
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)
    from tools.integration_catalog import _INTEGRATION_SAFETY_CONTRACT  # noqa: PLC0415

    return {group: dict(fields) for group, fields in _INTEGRATION_SAFETY_CONTRACT.items()}


def main() -> int:
    try:
        python_contract = _python_contract()
        swift_contract = _swift_contract(_read_swift())
    except (ImportError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    if python_contract != swift_contract:
        groups = sorted(set(python_contract) | set(swift_contract))
        for group in groups:
            expected = python_contract.get(group)
            actual = swift_contract.get(group)
            if expected != actual:
                print(
                    f"ERROR: contrato de seguridad distinto para {group}: Python={expected}, Swift={actual}"
                )
        return 1

    print(f"Contrato de seguridad móvil OK: {len(python_contract)} integraciones sincronizadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
