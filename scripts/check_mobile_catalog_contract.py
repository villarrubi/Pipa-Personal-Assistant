"""Check that structured catalog parameter kinds match Python and Swift."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SWIFT_VIEW_MODEL = REPO_ROOT / "mobile-ios" / "Sources" / "PipaMobileUI" / "PipaMobileViewModel.swift"
_SWIFT_STRING = re.compile(r'"([A-Za-z0-9_-]+)"')


def _read_swift() -> str:
    try:
        return SWIFT_VIEW_MODEL.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("No se pudo leer el modelo Swift del catálogo móvil.") from error


def _swift_parameter_kinds(source: str) -> set[str]:
    marker = "static let structuredParameterKinds: Set<String> = ["
    start = source.find(marker)
    if start < 0:
        raise ValueError("No se encontró la allowlist Swift de parámetros estructurados.")
    end = source.find("]", start + len(marker))
    if end < 0:
        raise ValueError("La allowlist Swift de parámetros estructurados no está cerrada.")
    values = set(_SWIFT_STRING.findall(source[start + len(marker) : end]))
    if not values:
        raise ValueError("La allowlist Swift de parámetros estructurados está vacía.")
    return values


def _python_parameter_kinds() -> set[str]:
    agent_path = str(REPO_ROOT / "windows-agent")
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)
    from tools.integration_catalog import _PARAMETER_KINDS, get_command_catalog  # noqa: PLC0415

    catalog_kinds = {
        parameter["kind"] for command in get_command_catalog() for parameter in command.get("parameters", [])
    }
    declared_kinds = set(_PARAMETER_KINDS)
    if catalog_kinds - declared_kinds:
        raise ValueError("El catálogo Python usa tipos de parámetros no declarados.")
    return declared_kinds


def main() -> int:
    try:
        python_kinds = _python_parameter_kinds()
        swift_kinds = _swift_parameter_kinds(_read_swift())
    except (ImportError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    missing = python_kinds - swift_kinds
    extra = swift_kinds - python_kinds
    if missing:
        print(f"ERROR: faltan tipos de parámetro en Swift: {', '.join(sorted(missing))}")
    if extra:
        print(f"ERROR: sobran tipos de parámetro en Swift: {', '.join(sorted(extra))}")
    if missing or extra:
        return 1

    print(f"Contrato de parámetros móvil OK: {len(python_kinds)} tipos sincronizados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
