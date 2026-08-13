"""Check that device confirmation labels stay identical across Python and Swift."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_CORE = REPO_ROOT / "backend" / "pipa_core" / "core.py"
SWIFT_VIEW_MODEL = REPO_ROOT / "mobile-ios" / "Sources" / "PipaMobileUI" / "PipaMobileViewModel.swift"
_SWIFT_ENTRY = re.compile(
    r'^\s*"(?P<key>(?:[^"\\]|\\.)+)"\s*:\s*'
    r'"(?P<value>(?:[^"\\]|\\.)*)"\s*,\s*$'
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"No se pudo leer {path.relative_to(REPO_ROOT)}.") from error


def _python_confirmation_map(source: str) -> dict[str, str]:
    try:
        tree = ast.parse(source, filename=str(BACKEND_CORE))
    except SyntaxError as error:
        raise ValueError("El núcleo Python no tiene sintaxis válida.") from error

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            targets = []
        if any(
            isinstance(target, ast.Name) and target.id == "_DEVICE_CONFIRMATION_SUMMARIES"
            for target in targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError) as error:
                raise ValueError("El mapa Python de confirmaciones no es literal.") from error
            if not isinstance(value, dict) or not all(
                isinstance(key, str) and isinstance(summary, str) for key, summary in value.items()
            ):
                raise ValueError("El mapa Python de confirmaciones no es un diccionario de texto.")
            return value
    raise ValueError("No se encontró _DEVICE_CONFIRMATION_SUMMARIES en el núcleo Python.")


def _swift_confirmation_map(source: str) -> dict[str, str]:
    marker = "private static let deviceConfirmationSummaries: [String: String] = ["
    start = source.find(marker)
    if start < 0:
        raise ValueError("No se encontró el mapa Swift de confirmaciones.")
    end = source.find("\n    ]", start + len(marker))
    if end < 0:
        raise ValueError("El mapa Swift de confirmaciones no está cerrado.")

    entries: dict[str, str] = {}
    for line in source[start + len(marker) : end].splitlines():
        match = _SWIFT_ENTRY.match(line)
        if match is None:
            continue
        try:
            key = ast.literal_eval(f'"{match.group("key")}"')
            value = ast.literal_eval(f'"{match.group("value")}"')
        except (ValueError, SyntaxError) as error:
            raise ValueError("El mapa Swift contiene una cadena no válida.") from error
        if key in entries:
            raise ValueError(f"La confirmación Swift está duplicada: {key}.")
        entries[key] = value
    if not entries:
        raise ValueError("El mapa Swift de confirmaciones está vacío.")
    return entries


def check_contract() -> tuple[set[str], set[str], set[str]]:
    python_map = _python_confirmation_map(_read(BACKEND_CORE))
    swift_map = _swift_confirmation_map(_read(SWIFT_VIEW_MODEL))
    missing_in_swift = set(python_map) - set(swift_map)
    extra_in_swift = set(swift_map) - set(python_map)
    mismatched = {key for key in set(python_map) & set(swift_map) if python_map[key] != swift_map[key]}
    return missing_in_swift, extra_in_swift, mismatched


def main() -> int:
    try:
        missing, extra, mismatched = check_contract()
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    if missing or extra or mismatched:
        if missing:
            print(f"ERROR: faltan confirmaciones Swift: {', '.join(sorted(missing))}")
        if extra:
            print(f"ERROR: sobran confirmaciones Swift: {', '.join(sorted(extra))}")
        if mismatched:
            print(f"ERROR: textos de confirmación distintos: {', '.join(sorted(mismatched))}")
        return 1

    print("Contrato de confirmaciones móvil OK: Python y Swift están sincronizados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
