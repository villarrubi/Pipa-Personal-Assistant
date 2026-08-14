"""Prepare the ignored local application allowlist safely.

The agent only reads ``config/apps.json``.  This helper is the explicit writer
for that file: it preserves existing entries, validates the complete result
with the same allowlist contract, rejects shell-mediated launchers, and only
writes after the user passes ``--write``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.apps import (  # noqa: E402
    DEFAULT_APPS_FILE,
    LOCAL_APPS_FILE,
    MAX_CONFIG_FILE_BYTES,
    AppsConfigError,
    validate_apps_config,
)

from backend.pipa_core.protocol import ProtocolError, parse_json_object  # noqa: E402


def _read_payload(path: Path) -> dict[str, Any]:
    """Read and validate either the local file or the public example seed."""

    source = path if path.exists() else DEFAULT_APPS_FILE
    try:
        with source.open("rb") as file:
            raw = file.read(MAX_CONFIG_FILE_BYTES + 1)
        if len(raw) > MAX_CONFIG_FILE_BYTES:
            raise ValueError("La configuración local es demasiado grande.")
        payload = parse_json_object(raw)
        validate_apps_config(payload)
        return payload
    except (OSError, UnicodeDecodeError, ProtocolError, AppsConfigError, ValueError) as error:
        raise ValueError("La configuración local de aplicaciones no es válida.") from error


def _clean_aliases(name: str, aliases: list[str] | None) -> list[str]:
    values = [item.strip() for item in (aliases or []) if isinstance(item, str) and item.strip()]
    return values or [name]


def _clean_command(launcher: str, arguments: list[str] | None) -> list[str]:
    if not isinstance(launcher, str) or not launcher.strip():
        raise ValueError("El lanzador directo es obligatorio.")
    cleaned = [launcher.strip()]
    for argument in arguments or []:
        if not isinstance(argument, str) or not argument.strip():
            raise ValueError("Los argumentos del lanzador no pueden estar vacíos.")
        cleaned.append(argument.strip())
    return cleaned


def build_app_payload(
    *,
    name: str,
    aliases: list[str] | None = None,
    launcher: str,
    arguments: list[str] | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a validated payload with one application replaced or added."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("El identificador de aplicación es obligatorio.")
    name = name.strip()
    payload = dict(existing or {})
    folded_name = name.casefold()
    for existing_name in list(payload):
        if isinstance(existing_name, str) and existing_name.casefold() == folded_name:
            del payload[existing_name]

    payload[name] = {
        "aliases": _clean_aliases(name, aliases),
        "command": _clean_command(launcher, arguments),
    }
    validate_apps_config(payload)
    return payload


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace the ignored local file and leave no temp file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".apps.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configura una aplicación local allowlisted para Pipa.")
    parser.add_argument("--name", help="Identificador local de la aplicación.")
    parser.add_argument("--alias", action="append", help="Alias adicional; puede repetirse.")
    parser.add_argument(
        "--launcher",
        help="Ejecutable o lanzador directo; no se permiten cmd, PowerShell ni shell wrappers.",
    )
    parser.add_argument(
        "--argument",
        action="append",
        help=("Argumento del lanzador; puede repetirse. Si empieza por '--', usa --argument=--opción."),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Escribe el archivo local. Sin esta opción solo valida y muestra un resumen.",
    )
    return parser


def _interactive_values(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.name:
        return {
            "name": arguments.name,
            "aliases": arguments.alias,
            "launcher": arguments.launcher,
            "arguments": arguments.argument,
        }

    name = input("Identificador local de la aplicación: ").strip()
    raw_aliases = input("Alias adicionales separados por coma (opcional): ").strip()
    aliases = [item.strip() for item in raw_aliases.split(",") if item.strip()] or None
    launcher = input("Ejecutable o lanzador directo: ").strip()
    command_arguments: list[str] = []
    while True:
        argument = input("Argumento adicional (Enter para terminar): ").strip()
        if not argument:
            break
        command_arguments.append(argument)
    return {
        "name": name,
        "aliases": aliases,
        "launcher": launcher,
        "arguments": command_arguments or None,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        values = _interactive_values(arguments)
        existing = _read_payload(LOCAL_APPS_FILE)
        payload = build_app_payload(existing=existing, **values)
        if arguments.write:
            _write_payload(LOCAL_APPS_FILE, payload)
            action = "guardada"
        else:
            action = "validada; no se ha escrito nada (usa --write para guardar)"
        configured = validate_apps_config(payload)
        app = next(
            app_data
            for app_id, app_data in configured.items()
            if app_id.casefold() == values["name"].strip().casefold()
        )
        print(f"Aplicación {action}. Argumentos configurados: {len(app['command']) - 1}.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Configuración cancelada.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("No se pudo validar o guardar la configuración local de aplicaciones.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
