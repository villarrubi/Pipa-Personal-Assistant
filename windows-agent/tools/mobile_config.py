"""Read-only validation for the opt-in mobile TCP configuration.

This module deliberately does not start a listener, touch the Registry, create
an identity, open a firewall rule, or return local paths. It mirrors the
gateway's fail-closed bind/port rules so a configuration can be checked before
the agent is restarted.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from secure_identity_store import SecureIdentityStore, SecureIdentityStoreError, default_secure_identity_path
from secure_tcp_gateway import DEFAULT_SERVER_ID, validate_mobile_bind_host, validate_mobile_port
from trusted_unlock_devices import DeviceStoreError, WindowsRegistryMobileDeviceStore

_IDENTITY_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _scope(value: str) -> str:
    address = ipaddress.ip_address(value)
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    return "private"


def inspect_mobile_transport(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return safe, bounded diagnostics for the current mobile configuration."""

    values = os.environ if environment is None else environment
    mode = values.get("PIPA_MOBILE_TRANSPORT", "").strip().lower() or "disabled"
    if mode in {"disabled", ""}:
        return {
            "success": True,
            "enabled": False,
            "mode": "disabled",
            "issues": [],
            "listener_started": False,
        }

    issues: list[str] = []
    if mode != "tcp-v2":
        issues.append("PIPA_MOBILE_TRANSPORT debe ser tcp-v2 o estar desactivado")

    bind_host = values.get("PIPA_MOBILE_BIND", "").strip()
    bind_scope = None
    if not bind_host:
        issues.append("falta PIPA_MOBILE_BIND")
    else:
        try:
            validate_mobile_bind_host(bind_host)
            bind_scope = _scope(bind_host)
        except ValueError:
            issues.append("PIPA_MOBILE_BIND no es una IP privada o loopback válida")

    port_value = values.get("PIPA_MOBILE_PORT", "").strip()
    port_configured = bool(port_value)
    if not port_configured:
        issues.append("falta PIPA_MOBILE_PORT")
    else:
        try:
            validate_mobile_port(port_value)
        except ValueError:
            issues.append("PIPA_MOBILE_PORT no es un puerto válido")

    server_id = values.get("PIPA_SECURE_SERVER_ID", DEFAULT_SERVER_ID).strip()
    if _IDENTITY_ID.fullmatch(server_id) is None:
        issues.append("PIPA_SECURE_SERVER_ID no tiene un identificador válido")

    identity_present = False
    identity_valid = False
    try:
        identity_path = Path(default_secure_identity_path())
        identity_present = identity_path.is_file()
        if identity_present:
            # Loading only validates the DPAPI envelope and identity metadata;
            # the private key is never returned by this diagnostic.
            SecureIdentityStore(identity_path).load(server_id)
            identity_valid = True
        else:
            issues.append("falta la identidad segura protegida del agente")
    except (OSError, SecureIdentityStoreError):
        if identity_present:
            issues.append("la identidad segura no se pudo validar")
        else:
            issues.append("falta la identidad segura protegida del agente")

    paired_devices_checked = False
    paired_devices_present = False
    try:
        paired_devices = WindowsRegistryMobileDeviceStore().trusted_public_keys()
        paired_devices_checked = True
        paired_devices_present = bool(paired_devices)
        if not paired_devices_present:
            issues.append("no hay dispositivos móviles emparejados")
    except (DeviceStoreError, OSError, ValueError):
        issues.append("no se pudo comprobar el almacén de dispositivos móviles")

    return {
        "success": not issues,
        "enabled": True,
        "mode": mode,
        "bind_scope": bind_scope,
        "port_configured": port_configured,
        "identity_present": identity_present,
        "identity_valid": identity_valid,
        "paired_devices_checked": paired_devices_checked,
        "paired_devices_present": paired_devices_present,
        "issues": issues,
        "listener_started": False,
    }
