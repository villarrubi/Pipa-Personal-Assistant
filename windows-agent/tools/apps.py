import json
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
APPS_FILE = BASE_DIR / "config" / "apps.json"


def load_apps():
    with open(APPS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def find_app(app_name: str):
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

    except Exception as error:
        return {
            "success": False,
            "app": app_id,
            "message": f"No he podido abrir '{app_id}'.",
            "error": str(error)
        }