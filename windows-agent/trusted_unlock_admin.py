"""Administrator CLI for pairing and revoking Pipa trusted devices.

This tool accepts and stores public keys only.  It never generates or imports
private keys on the Windows PC.
"""

from __future__ import annotations

import argparse
import sys

from trusted_unlock_devices import (
    DeviceAlreadyRegisteredError,
    DeviceNotFoundError,
    DeviceStoreError,
    WindowsRegistryDeviceStore,
    is_administrator,
    public_key_fingerprint,
    public_key_from_base64,
    validate_device_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipa Trusted Unlock device administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pair = subparsers.add_parser("pair", help="register an Ed25519 public key")
    pair.add_argument("--device-id", required=True)
    pair.add_argument("--public-key", required=True, help="raw Ed25519 public key, base64url")

    revoke = subparsers.add_parser("revoke", help="remove a registered device")
    revoke.add_argument("--device-id", required=True)
    revoke.add_argument("--yes", action="store_true", help="confirm the revocation")

    subparsers.add_parser("list", help="list registered devices")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        store = WindowsRegistryDeviceStore()

        if args.command == "list":
            devices = store.list_devices()
            if not devices:
                print("No hay dispositivos Pipa emparejados.")
                return 0
            for device in devices:
                print(
                    f"{device.device_id}\tcreado={device.created_at}"
                    f"\tfingerprint={device.fingerprint}"
                )
            return 0

        if not is_administrator():
            raise DeviceStoreError(
                "pair/revoke debe ejecutarse desde PowerShell como administrador"
            )

        device_id = validate_device_id(args.device_id)

        if args.command == "pair":
            public_key = public_key_from_base64(args.public_key)
            device = store.register(device_id, public_key)
            print(f"Dispositivo Pipa emparejado: {device.device_id}")
            print(f"Fingerprint: {public_key_fingerprint(device.public_key)}")
            return 0

        if args.command == "revoke":
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
