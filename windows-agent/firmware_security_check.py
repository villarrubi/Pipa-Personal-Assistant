"""Read-only ESP32-S3 eFuse gate for the development flasher.

The checker intentionally asks ``espefuse`` for only the three security
fields needed to decide whether a plaintext development image is safe to
attempt. It never invokes a burn command, never stores the raw report and
never returns MAC addresses, key digests or other eFuse contents.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_PORT_PATTERN = re.compile(r"^COM[1-9][0-9]{0,2}$", re.IGNORECASE)
_REQUIRED_FIELDS = ("SPI_BOOT_CRYPT_CNT", "SECURE_BOOT_EN", "SECURE_VERSION")
_MAX_TOOL_OUTPUT = 64 * 1024
_TOOL_TIMEOUT_SECONDS = 45


def validate_port(value: str) -> str:
    """Validate one explicit Windows serial port without accepting aliases."""

    port = value.strip().upper() if isinstance(value, str) else ""
    if _PORT_PATTERN.fullmatch(port) is None:
        raise ValueError("El puerto debe ser COM1 a COM999.")
    return port


def _extract_json(output: str) -> Mapping[str, Any]:
    """Extract the final JSON object while ignoring tool banners."""

    if not isinstance(output, str) or len(output) > _MAX_TOOL_OUTPUT:
        raise ValueError("efuse output exceeded the bounded limit")
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise ValueError("efuse output did not contain a JSON object")
    value = json.loads(output[start : end + 1])
    if not isinstance(value, Mapping):
        raise ValueError("efuse report was not an object")
    return value


def parse_summary_json(output: str) -> dict[str, Any]:
    """Keep only the required eFuse values and reject incomplete reports."""

    raw = _extract_json(output)
    fields: dict[str, Any] = {}
    for name in _REQUIRED_FIELDS:
        field = raw.get(name)
        if not isinstance(field, Mapping) or "value" not in field:
            raise ValueError(f"missing eFuse field: {name}")
        fields[name] = field["value"]
    return fields


def _secure_boot_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("SECURE_BOOT_EN was not boolean")


def _flash_encryption_enabled(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized == "enable":
            return True
        if normalized == "disable":
            return False
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1, 3, 7}:
            return value != 0
    raise ValueError("SPI_BOOT_CRYPT_CNT had an unknown value")


def evaluate_security(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether a plaintext development image may be attempted."""

    secure_boot = _secure_boot_enabled(fields["SECURE_BOOT_EN"])
    flash_encryption = _flash_encryption_enabled(fields["SPI_BOOT_CRYPT_CNT"])
    secure_version = fields["SECURE_VERSION"]
    if not isinstance(secure_version, int) or isinstance(secure_version, bool) or secure_version < 0:
        raise ValueError("SECURE_VERSION was not a non-negative integer")

    failures: list[str] = []
    if secure_boot:
        failures.append("secure_boot_enabled")
    if flash_encryption:
        failures.append("flash_encryption_enabled")
    if secure_version != 0:
        failures.append("anti_rollback_version_nonzero")

    return {
        "success": not failures,
        "read_only": True,
        "secure_boot_enabled": secure_boot,
        "flash_encryption_enabled": flash_encryption,
        "secure_version": secure_version,
        "failures": failures,
    }


def read_security_state(
    port: str,
    *,
    python_executable: str,
    espefuse_path: str,
) -> dict[str, Any]:
    """Read the filtered security fields through the vendor tool."""

    command = [
        python_executable,
        espefuse_path,
        "--chip",
        "esp32s3",
        "--port",
        validate_port(port),
        "--before",
        "default-reset",
        "--after",
        "no-reset",
        "summary",
        "--format",
        "json",
        *_REQUIRED_FIELDS,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise RuntimeError("no se pudo consultar el estado de seguridad del dispositivo") from error
    if completed.returncode != 0:
        raise RuntimeError("espefuse no pudo leer el estado de seguridad del dispositivo")
    return evaluate_security(parse_summary_json(completed.stdout))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sonda de seguridad eFuse en modo solo lectura.")
    parser.add_argument("--port", required=True, type=validate_port)
    parser.add_argument("--python", dest="python_executable", required=True)
    parser.add_argument("--espefuse", dest="espefuse_path", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = read_security_state(
            arguments.port,
            python_executable=str(Path(arguments.python_executable)),
            espefuse_path=str(Path(arguments.espefuse_path)),
        )
    except (RuntimeError, ValueError):
        report = {
            "success": False,
            "read_only": True,
            "failures": ["security_state_unavailable"],
        }
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif report["success"]:
        print("Estado eFuse compatible con imagen de desarrollo; lectura solo lectura.")
    else:
        print("No se puede autorizar una imagen de desarrollo sobre este estado eFuse.", file=sys.stderr)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
