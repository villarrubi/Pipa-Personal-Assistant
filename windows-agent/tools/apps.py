import json
import subprocess
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_APPS_FILE = CONFIG_DIR / "apps.json"
DEFAULT_APPS_FILE = CONFIG_DIR / "apps.example.json"


class AppsConfigError(ValueError):
    """La configuración de aplicaciones falta o no tiene el formato esperado."""


def _get_apps_file() -> Path:
    return LOCAL_APPS_FILE if LOCAL_APPS_FILE.exists() else DEFAULT_APPS_FILE


def validate_apps_config(apps: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(apps, dict):
        raise AppsConfigError("La configuración de aplicaciones debe ser un objeto JSON.")

    validated: dict[str, dict[str, list[str]]] = {}
    for app_id, app_data in apps.items():
        if not isinstance(app_id, str) or not isinstance(app_data, dict):
            raise AppsConfigError("Cada aplicación debe tener un identificador y un objeto.")

        aliases = app_data.get("aliases")
        command = app_data.get("command")
        if (
            not isinstance(aliases, list)
            or not aliases
            or not all(isinstance(alias, str) and alias.strip() for alias in aliases)
            or not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) for argument in command)
        ):
            raise AppsConfigError(f"Configuración inválida para la aplicación '{app_id}'.")

        validated[app_id] = {
            "aliases": aliases,
            "command": command,
        }

    return validated


def load_apps() -> dict[str, dict[str, list[str]]]:
    apps_file = _get_apps_file()
    try:
        with open(apps_file, "r", encoding="utf-8") as file:
            return validate_apps_config(json.load(file))
    except FileNotFoundError as error:
        raise AppsConfigError(f"No existe la configuración: {apps_file}") from error
    except json.JSONDecodeError as error:
        raise AppsConfigError(f"JSON inválido en {apps_file}: {error.msg}") from error


def find_app(app_name: str) -> tuple[str | None, dict[str, list[str]] | None]:
    app_name = app_name.lower().strip()
    apps = load_apps()

    for app_id, app_data in apps.items():
        aliases = [alias.lower() for alias in app_data["aliases"]]

        if app_name == app_id.lower() or app_name in aliases:
            return app_id, app_data

    return None, None


def open_app(app_name: str):
    app_id, app_data = find_app(app_name)

    if app_data is None:
        return {
            "success": False,
            "message": f"No conozco la aplicación '{app_name}'."
        }

    try:
        subprocess.Popen(app_data["command"])

        return {
            "success": True,
            "app": app_id,
            "message": f"Aplicación '{app_id}' abierta."
        }

    except OSError as error:
        return {
            "success": False,
            "app": app_id,
            "message": f"No he podido abrir '{app_id}'.",
            "error": str(error)
        }
