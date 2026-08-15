"""Private, local configuration used by the Pipα control panel.

The JSON file contains presentation preferences and non-secret WhatsApp Cloud
API metadata. Access tokens never enter that file: on Windows they live in the
current user's Credential Manager, with an environment variable as the
deployment-friendly alternative.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from tools.text_policy import validate_bounded_text

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_CONTROL_FILE = CONFIG_DIR / "control-panel.local.json"
MAX_CONTROL_FILE_BYTES = 64 * 1024
MAX_COMMAND_OVERRIDES = 64
WHATSAPP_CREDENTIAL_TARGET = "Pipa/WhatsAppCloudApi"
# This is an environment-variable name, never a credential value.
WHATSAPP_TOKEN_ENV = "PIPA_WHATSAPP_ACCESS_TOKEN"  # nosec B105
_COMMAND_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_PHONE_NUMBER_ID = re.compile(r"^[0-9]{5,32}$")
_API_VERSION = re.compile(r"^v[1-9][0-9]{0,2}\.[0-9]{1,2}$")

_DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "commands": {},
    "whatsapp": {
        "mode": "manual",
        "phone_number_id": "",
        "api_version": "v23.0",
    },
}


class ControlConfigError(ValueError):
    """The private control-panel configuration is unavailable or invalid."""


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ControlConfigError("La configuración del panel contiene claves duplicadas.")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    if not isinstance(value, dict):
        raise ControlConfigError("La configuración del panel no es un objeto.")
    return value


def _validate_command_preferences(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(value) > MAX_COMMAND_OVERRIDES:
        raise ControlConfigError("La configuración de comandos no es válida.")

    result: dict[str, dict[str, Any]] = {}
    for command_id, preference in value.items():
        if (
            not isinstance(command_id, str)
            or _COMMAND_ID.fullmatch(command_id) is None
            or not isinstance(preference, dict)
            or set(preference) - {"enabled", "phrase"}
        ):
            raise ControlConfigError("La configuración de comandos no es válida.")
        enabled = preference.get("enabled", True)
        phrase = preference.get("phrase")
        if not isinstance(enabled, bool) or (phrase is not None and not isinstance(phrase, str)):
            raise ControlConfigError("La configuración de comandos no es válida.")

        normalized: dict[str, Any] = {"enabled": enabled}
        if phrase is not None:
            try:
                normalized_phrase = validate_bounded_text(phrase, "La frase", 256).strip()
            except ValueError as error:
                raise ControlConfigError("La frase del comando no es válida.") from error
            if not normalized_phrase:
                raise ControlConfigError("La frase del comando no es válida.")
            normalized["phrase"] = normalized_phrase
        result[command_id] = normalized
    return result


def _validate_whatsapp_settings(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"mode", "phone_number_id", "api_version"}:
        raise ControlConfigError("La configuración de WhatsApp no es válida.")
    mode = value.get("mode", "manual")
    phone_number_id = value.get("phone_number_id", "")
    api_version = value.get("api_version", "v23.0")
    if (
        mode not in {"manual", "cloud_api"}
        or not isinstance(phone_number_id, str)
        or (phone_number_id and _PHONE_NUMBER_ID.fullmatch(phone_number_id) is None)
        or not isinstance(api_version, str)
        or _API_VERSION.fullmatch(api_version) is None
    ):
        raise ControlConfigError("La configuración de WhatsApp no es válida.")
    return {
        "mode": mode,
        "phone_number_id": phone_number_id,
        "api_version": api_version,
    }


def validate_control_config(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"version", "commands", "whatsapp"}:
        raise ControlConfigError("La configuración del panel no es válida.")
    if value.get("version", 1) != 1:
        raise ControlConfigError("La versión de configuración del panel no es compatible.")
    return {
        "version": 1,
        "commands": _validate_command_preferences(value.get("commands", {})),
        "whatsapp": _validate_whatsapp_settings(value.get("whatsapp", {})),
    }


def load_control_config() -> dict[str, Any]:
    if not LOCAL_CONTROL_FILE.exists():
        return deepcopy(_DEFAULT_CONFIG)
    try:
        with LOCAL_CONTROL_FILE.open("rb") as file:
            raw = file.read(MAX_CONTROL_FILE_BYTES + 1)
        if len(raw) > MAX_CONTROL_FILE_BYTES:
            raise ControlConfigError("La configuración del panel es demasiado grande.")
        return validate_control_config(_parse_json_object(raw))
    except FileNotFoundError:
        return deepcopy(_DEFAULT_CONFIG)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ControlConfigError("No se pudo leer la configuración del panel.") from error


def save_control_config(value: object) -> dict[str, Any]:
    validated = validate_control_config(value)
    encoded = (json.dumps(validated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_CONTROL_FILE_BYTES:
        raise ControlConfigError("La configuración del panel es demasiado grande.")

    LOCAL_CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".control-panel.",
            suffix=".tmp",
            dir=LOCAL_CONTROL_FILE.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, LOCAL_CONTROL_FILE)
        temporary_path = None
    except OSError as error:
        raise ControlConfigError("No se pudo guardar la configuración del panel.") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return validated


def get_command_preferences() -> dict[str, dict[str, Any]]:
    return load_control_config()["commands"]


def set_command_preference(command_id: str, *, enabled: bool, phrase: str | None) -> None:
    config = load_control_config()
    preference: dict[str, Any] = {"enabled": enabled}
    if phrase is not None:
        preference["phrase"] = phrase
    config["commands"][command_id] = preference
    save_control_config(config)


def reset_command_preference(command_id: str) -> None:
    config = load_control_config()
    config["commands"].pop(command_id, None)
    save_control_config(config)


def get_whatsapp_settings() -> dict[str, str]:
    return load_control_config()["whatsapp"]


def set_whatsapp_settings(*, mode: str, phone_number_id: str, api_version: str) -> None:
    config = load_control_config()
    config["whatsapp"] = {
        "mode": mode,
        "phone_number_id": phone_number_id,
        "api_version": api_version,
    }
    save_control_config(config)


def _environment_access_token() -> str | None:
    value = os.environ.get(WHATSAPP_TOKEN_ENV, "").strip()
    return value or None


def _credential_manager_access_token() -> str | None:
    if os.name != "nt":
        return None
    try:
        import win32cred

        credential = win32cred.CredRead(WHATSAPP_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
        blob = credential.get("CredentialBlob")
        if isinstance(blob, bytes):
            value = blob.decode("utf-16-le").rstrip("\x00")
        elif isinstance(blob, str):
            value = blob
        else:
            return None
        return value.strip() or None
    except Exception:
        # A missing credential and an unavailable Windows credential service
        # are equivalent to callers. Never include its exception text.
        return None


def get_whatsapp_access_token() -> str | None:
    return _environment_access_token() or _credential_manager_access_token()


def whatsapp_credential_source() -> str:
    if _environment_access_token() is not None:
        return "environment"
    if _credential_manager_access_token() is not None:
        return "windows_credential_manager"
    return "none"


def store_whatsapp_access_token(access_token: str) -> None:
    try:
        token = validate_bounded_text(access_token, "El token", 4096).strip()
    except ValueError as error:
        raise ControlConfigError("El token de WhatsApp no es válido.") from error
    if len(token) < 20:
        raise ControlConfigError("El token de WhatsApp no es válido.")
    if os.name != "nt":
        raise ControlConfigError("El almacén seguro de Windows no está disponible.")
    try:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": WHATSAPP_CREDENTIAL_TARGET,
                "UserName": "Pipa",
                "CredentialBlob": token,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "Comment": "WhatsApp Cloud API para Pipα",
            },
            0,
        )
    except Exception as error:
        raise ControlConfigError("No se pudo guardar el token en Credenciales de Windows.") from error


def delete_whatsapp_access_token() -> None:
    if _environment_access_token() is not None:
        raise ControlConfigError("El token procede del entorno y no se puede borrar desde el panel.")
    if os.name != "nt":
        return
    try:
        import win32cred

        win32cred.CredDelete(WHATSAPP_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
    except Exception as error:
        # Windows uses ERROR_NOT_FOUND (1168) for an already-missing generic
        # credential; other failures must not be reported as a successful wipe.
        error_code = getattr(error, "winerror", None)
        if error_code is None and getattr(error, "args", ()):
            error_code = error.args[0]
        if error_code == 1168:
            return
        raise ControlConfigError("No se pudo borrar el token de Credenciales de Windows.") from error


def whatsapp_automatic_send_active() -> bool:
    settings = get_whatsapp_settings()
    return bool(
        settings["mode"] == "cloud_api" and settings["phone_number_id"] and get_whatsapp_access_token()
    )


def get_whatsapp_public_status() -> dict[str, object]:
    settings = get_whatsapp_settings()
    source = whatsapp_credential_source()
    return {
        "mode": settings["mode"],
        "automatic_send": settings["mode"] == "cloud_api",
        "active": whatsapp_automatic_send_active(),
        "phone_number_id": settings["phone_number_id"],
        "api_version": settings["api_version"],
        "credential_configured": source != "none",
        "credential_source": source,
    }
