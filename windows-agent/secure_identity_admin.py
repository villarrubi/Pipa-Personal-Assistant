"""Local, public-only administration for the secure agent identity.

The commands never print or export the private Ed25519 key. ``init`` is the
only command that may create the DPAPI-protected identity file; ``show`` and
``firmware-snippet`` are read-only and are intended for out-of-band key
provisioning after the operator verifies the displayed fingerprint.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from secure_identity_store import (
    SecureIdentityStore,
    SecureIdentityStoreError,
    default_secure_identity_path,
)
from trusted_unlock_devices import public_key_fingerprint

DEFAULT_SERVER_ID = "pipa-agent-v2"


def _identity_id(value: str | None) -> str:
    identity_id = (value or os.environ.get("PIPA_SECURE_SERVER_ID") or DEFAULT_SERVER_ID).strip()
    if not identity_id:
        raise ValueError("identity_id no puede estar vacío")
    return identity_id


def _details(identity) -> dict[str, str]:
    public_key = identity.public_key_b64
    return {
        "identity_id": identity.identity_id,
        "public_key": public_key,
        "fingerprint": public_key_fingerprint(public_key),
    }


def _firmware_snippet(identity) -> str:
    details = _details(identity)
    return "\n".join(
        (
            "// Public key only; keep the DPAPI identity file on Windows.",
            "#define PIPA_SECURE_SESSION_ENABLED 1",
            f'#define PIPA_SECURE_SERVER_ID "{details["identity_id"]}"',
            f'#define PIPA_SECURE_SERVER_PUBLIC_KEY "{details["public_key"]}"',
            f"// Fingerprint: {details['fingerprint']}",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Identidad segura v2 de Pipa (solo clave pública en salida)."
    )
    parser.add_argument("--identity-id", help=f"Identificador del agente (por defecto: {DEFAULT_SERVER_ID}).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Crea la identidad protegida por DPAPI si no existe.")
    commands.add_parser("show", help="Muestra identidad pública y fingerprint sin crearla.")
    commands.add_parser(
        "firmware-snippet", help="Muestra defines públicos para el fichero local del firmware."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        identity_id = _identity_id(arguments.identity_id)
        path = default_secure_identity_path()
        store = SecureIdentityStore(path)
        if arguments.command == "init":
            identity = store.load_or_create(identity_id)
            print(json.dumps({"created_or_loaded": True, **_details(identity)}, ensure_ascii=False, indent=2))
            return 0
        identity = store.load(identity_id)
        if arguments.command == "show":
            print(json.dumps(_details(identity), ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "firmware-snippet":
            print(_firmware_snippet(identity))
            return 0
        raise ValueError("comando no soportado")
    except (SecureIdentityStoreError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
