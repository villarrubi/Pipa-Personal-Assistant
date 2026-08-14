import os
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from backend.pipa_core.protocol import ProtocolError, parse_json_object

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_APPS_FILE = CONFIG_DIR / "apps.json"
DEFAULT_APPS_FILE = CONFIG_DIR / "apps.example.json"
MAX_APP_ID_LENGTH = 64
MAX_APPS = 64
MAX_CONFIG_FILE_BYTES = 128 * 1024
MAX_ALIASES_PER_APP = 32
MAX_ALIAS_LENGTH = 80
MAX_COMMAND_ARGUMENTS = 32
MAX_COMMAND_ARGUMENT_LENGTH = 1024
_BLOCKED_LAUNCHERS = frozenset(
    {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "wscript",
        "wscript.exe",
        "cscript",
        "cscript.exe",
        "bash",
        "bash.exe",
        "sh",
        "sh.exe",
        # Common interpreters and Windows execution proxies are not desktop
        # applications. Allowing them here would turn an app alias into an
        # arbitrary script/code execution primitive, even with shell=False.
        "python",
        "python.exe",
        "python3",
        "python3.exe",
        "py",
        "py.exe",
        "node",
        "node.exe",
        "nodejs",
        "nodejs.exe",
        "perl",
        "perl.exe",
        "ruby",
        "ruby.exe",
        "php",
        "php.exe",
        "java",
        "java.exe",
        "javaw",
        "javaw.exe",
        "dotnet",
        "dotnet.exe",
        "wsl",
        "wsl.exe",
        "mshta",
        "mshta.exe",
        "rundll32",
        "rundll32.exe",
        "regsvr32",
        "regsvr32.exe",
        "installutil",
        "installutil.exe",
    }
)
_BLOCKED_SHELL_SWITCHES = frozenset({"/c", "/k", "-command", "-encodedcommand", "-file"})
_BLOCKED_SCRIPT_SUFFIXES = frozenset(
    {".bat", ".cmd", ".hta", ".js", ".jse", ".ps1", ".psm1", ".sh", ".vbe", ".vbs", ".wsh", ".wsf"}
)


def _is_forbidden_label_character(character: str) -> bool:
    """Reject invisible/control characters from app IDs and aliases."""

    return unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"}


def _uses_shell_launcher(command: list[str]) -> bool:
    """Reject shell-mediated app entries from the local allowlist.

    The app configuration is intentionally a list passed directly to
    ``Popen``.  A shell launcher would turn a harmless-looking alias into an
    interpreter boundary and could also recreate visible console windows.
    Applications must be launched directly (for example ``explorer.exe``
    with a ``shell:AppsFolder`` argument).
    """

    launcher_path = Path(command[0])
    launcher = launcher_path.name.casefold()
    return (
        launcher in _BLOCKED_LAUNCHERS
        or launcher_path.suffix.casefold() in _BLOCKED_SCRIPT_SUFFIXES
        or any(argument.casefold() in _BLOCKED_SHELL_SWITCHES for argument in command[1:])
    )


def resolve_launcher(launcher: str) -> str | None:
    """Resolve a configured launcher to a non-script executable.

    ``Popen(..., shell=False)`` is not enough to make Windows batch files a
    non-shell boundary: Windows can dispatch ``.cmd``/``.bat`` files through a
    command interpreter anyway. Resolve the executable first and reject both
    explicitly configured scripts and names such as ``code`` that resolve to a
    script on ``PATH``.
    """

    if not isinstance(launcher, str) or not launcher or _uses_shell_launcher([launcher]):
        return None
    resolved = shutil.which(launcher)
    if resolved is None or _uses_shell_launcher([resolved]):
        return None
    return resolved


class AppsConfigError(ValueError):
    """La configuración de aplicaciones falta o no tiene el formato esperado."""


def _get_apps_file() -> Path:
    return LOCAL_APPS_FILE if LOCAL_APPS_FILE.exists() else DEFAULT_APPS_FILE


def validate_apps_config(apps: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(apps, dict) or len(apps) > MAX_APPS:
        raise AppsConfigError("La configuración de aplicaciones debe ser un objeto de tamaño limitado.")

    validated: dict[str, dict[str, list[str]]] = {}
    seen_labels: dict[str, str] = {}
    for app_id, app_data in apps.items():
        if (
            not isinstance(app_id, str)
            or not app_id.strip()
            or app_id != app_id.strip()
            or len(app_id) > MAX_APP_ID_LENGTH
            or any(_is_forbidden_label_character(character) for character in app_id)
            or not isinstance(app_data, dict)
        ):
            raise AppsConfigError("Cada aplicación debe tener un identificador y un objeto.")

        aliases = app_data.get("aliases")
        command = app_data.get("command")
        if (
            not isinstance(aliases, list)
            or not aliases
            or len(aliases) > MAX_ALIASES_PER_APP
            or not all(isinstance(alias, str) and alias.strip() for alias in aliases)
            or not all(
                alias == alias.strip()
                and len(alias) <= MAX_ALIAS_LENGTH
                and not any(_is_forbidden_label_character(character) for character in alias)
                for alias in aliases
            )
            or not isinstance(command, list)
            or not command
            or len(command) > MAX_COMMAND_ARGUMENTS
            or not all(isinstance(argument, str) and argument for argument in command)
            or not all(
                len(argument) <= MAX_COMMAND_ARGUMENT_LENGTH
                and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in argument)
                for argument in command
            )
            or _uses_shell_launcher(command)
        ):
            raise AppsConfigError(f"Configuración inválida para la aplicación '{app_id}'.")

        app_folded = app_id.casefold()
        if app_folded in seen_labels:
            raise AppsConfigError(f"El nombre o alias '{app_id}' está repetido.")
        seen_labels[app_folded] = app_id
        seen_aliases: set[str] = set()
        for alias in aliases:
            folded = alias.casefold()
            if folded == app_folded:
                if folded in seen_aliases:
                    raise AppsConfigError(f"El nombre o alias '{alias}' está repetido.")
                seen_aliases.add(folded)
                continue
            if folded in seen_labels:
                raise AppsConfigError(f"El nombre o alias '{alias}' está repetido.")
            seen_labels[folded] = app_id

        validated[app_id] = {
            "aliases": aliases,
            "command": command,
        }

    return validated


def load_apps() -> dict[str, dict[str, list[str]]]:
    apps_file = _get_apps_file()
    try:
        with open(apps_file, "rb") as file:
            raw = file.read(MAX_CONFIG_FILE_BYTES + 1)
        if len(raw) > MAX_CONFIG_FILE_BYTES:
            raise AppsConfigError("La configuración de aplicaciones es demasiado grande.")
        return validate_apps_config(parse_json_object(raw))
    except FileNotFoundError as error:
        raise AppsConfigError(f"No existe la configuración: {apps_file}") from error
    except OSError as error:
        raise AppsConfigError("No se pudo leer la configuración de aplicaciones.") from error
    except UnicodeDecodeError as error:
        raise AppsConfigError("La configuración de aplicaciones no es UTF-8 válido.") from error
    except ProtocolError as error:
        raise AppsConfigError(f"JSON inválido en {apps_file}.") from error


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
        return {"success": False, "message": f"No conozco la aplicación '{app_name}'."}

    launcher = resolve_launcher(app_data["command"][0])
    if launcher is None:
        return {
            "success": False,
            "app": app_id,
            "message": f"No he podido resolver el lanzador de '{app_id}'.",
        }

    try:
        popen_options = {}
        if os.name == "nt":
            # Keep configured console applications from flashing a window when
            # the agent runs invisibly. Prefer direct launchers in the example
            # configuration instead of routing through cmd.exe.
            popen_options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([launcher, *app_data["command"][1:]], **popen_options)

        return {"success": True, "app": app_id, "message": f"Aplicación '{app_id}' abierta."}

    except OSError:
        return {
            "success": False,
            "app": app_id,
            "message": f"No he podido abrir '{app_id}'.",
        }
