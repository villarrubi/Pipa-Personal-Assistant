"""Administrator CLI for pairing and revoking Pipa trusted devices.

This tool accepts and stores public keys only.  It never generates or imports
private keys on the Windows PC.
"""

from __future__ import annotations

import argparse
import hmac
import re
import sys

from trusted_unlock_devices import (
    DeviceAlreadyRegisteredError,
    DeviceNotFoundError,
    DeviceStoreError,
    WindowsRegistryDeviceStore,
    WindowsRegistryMobileDeviceStore,
    is_administrator,
    public_key_fingerprint,
    public_key_from_base64,
    validate_device_id,
)

_FINGERPRINT_HEX = re.compile(r"^[0-9A-F]{64}$")


def _normalize_public_key_option(argv: list[str]) -> list[str]:
    """Keep base64url keys beginning with '-' parseable by argparse."""

    normalized: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--public-key" and index + 1 < len(argv):
            normalized.append(f"--public-key={argv[index + 1]}")
            index += 2
            continue
        normalized.append(value)
        index += 1
    return normalized


def normalize_fingerprint(value: str) -> str:
    """Return the canonical colon-separated SHA-256 fingerprint form."""

    if not isinstance(value, str):
        raise ValueError("fingerprint must be text")
    compact = value.replace(":", "").replace(" ", "").replace("-", "").upper()
    if _FINGERPRINT_HEX.fullmatch(compact) is None:
        raise ValueError("fingerprint must contain exactly 64 hexadecimal characters")
    return ":".join(compact[index : index + 2] for index in range(0, len(compact), 2))


def verify_expected_fingerprint(public_key_b64: str, expected_fingerprint: str) -> str:
    """Verify before touching the Registry and return the actual fingerprint."""

    actual = public_key_fingerprint(public_key_b64)
    expected = normalize_fingerprint(expected_fingerprint)
    if not hmac.compare_digest(actual, expected):
        raise DeviceStoreError("fingerprint does not match; Registry was not changed")
    return actual


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipa Trusted Unlock device administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_pair_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--device-id", required=True)
        command.add_argument("--public-key", required=True, help="raw Ed25519 public key, base64url")
        command.add_argument(
            "--expected-fingerprint",
            required=True,
            help="fingerprint compared with the device before registration",
        )

    pair = subparsers.add_parser("pair", help="register a Waveshare/Trusted Unlock public key")
    add_pair_arguments(pair)
    pair_mobile = subparsers.add_parser("pair-mobile", help="register a mobile command public key")
    add_pair_arguments(pair_mobile)

    fingerprint = subparsers.add_parser(
        "fingerprint",
        help="calculate a public-key fingerprint without changing the Registry",
    )
    fingerprint.add_argument("--public-key", required=True, help="raw Ed25519 public key, base64url")

    revoke = subparsers.add_parser("revoke", help="remove a registered device")
    revoke.add_argument("--device-id", required=True)
    revoke.add_argument("--yes", action="store_true", help="confirm the revocation")

    revoke_mobile = subparsers.add_parser("revoke-mobile", help="remove a registered mobile device")
    revoke_mobile.add_argument("--device-id", required=True)
    revoke_mobile.add_argument("--yes", action="store_true", help="confirm the revocation")

    subparsers.add_parser("list", help="list registered devices")
    subparsers.add_parser("list-mobile", help="list registered mobile devices")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(_normalize_public_key_option(raw_args))

    try:
        if args.command == "fingerprint":
            public_key_from_base64(args.public_key)
            print(f"Fingerprint: {public_key_fingerprint(args.public_key)}")
            return 0

        mobile_command = args.command in {"pair-mobile", "revoke-mobile", "list-mobile"}
        store = WindowsRegistryMobileDeviceStore() if mobile_command else WindowsRegistryDeviceStore()

        if args.command in {"list", "list-mobile"}:
            devices = store.list_devices()
            if not devices:
                label = "móviles" if args.command == "list-mobile" else "Pipa"
                print(f"No hay dispositivos {label} emparejados.")
                return 0
            for device in devices:
                print(f"{device.device_id}\tcreado={device.created_at}\tfingerprint={device.fingerprint}")
            return 0

        if not is_administrator():
            raise DeviceStoreError("pair/revoke debe ejecutarse desde PowerShell como administrador")

        device_id = validate_device_id(args.device_id)

        if args.command in {"pair", "pair-mobile"}:
            public_key = public_key_from_base64(args.public_key)
            actual_fingerprint = verify_expected_fingerprint(args.public_key, args.expected_fingerprint)
            device = store.register(device_id, public_key)
            label = "móvil" if args.command == "pair-mobile" else "Pipa"
            print(f"Dispositivo {label} emparejado: {device.device_id}")
            print(f"Fingerprint: {actual_fingerprint}")
            return 0

        if args.command in {"revoke", "revoke-mobile"}:
            if not args.yes:
                raise DeviceStoreError("revoke requiere --yes para confirmar")
            store.revoke(device_id)
            print(f"Dispositivo revocado: {device_id}")
            return 0

        raise DeviceStoreError(f"comando no soportado: {args.command}")
    except (DeviceStoreError, ValueError, DeviceAlreadyRegisteredError, DeviceNotFoundError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
