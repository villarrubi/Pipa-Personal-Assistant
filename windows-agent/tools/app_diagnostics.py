"""Read-only diagnostics for the local application allowlist."""

from __future__ import annotations

from typing import Any

from tools.apps import AppsConfigError, load_apps, resolve_launcher


def launcher_resolved(launcher: str) -> bool:
    """Check availability without starting the configured process."""

    return resolve_launcher(launcher) is not None


def inspect_apps() -> dict[str, Any]:
    """Return bounded app readiness without exposing commands or paths."""

    try:
        apps = load_apps()
    except AppsConfigError:
        return {
            "success": False,
            "ready": False,
            "configured_count": 0,
            "unresolved_count": 0,
            "apps": {},
            "error": "apps_config_invalid",
        }

    statuses: dict[str, dict[str, object]] = {}
    unresolved = 0
    for app_id, app_data in apps.items():
        resolved = launcher_resolved(app_data["command"][0])
        if not resolved:
            unresolved += 1
        statuses[app_id] = {
            "launcher_resolved": resolved,
            "argument_count": len(app_data["command"]) - 1,
        }
    return {
        "success": True,
        "ready": unresolved == 0,
        "configured_count": len(statuses),
        "unresolved_count": unresolved,
        "apps": statuses,
    }
