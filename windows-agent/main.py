import asyncio
import logging
import os
import platform
import sys
import webbrowser
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.app_diagnostics import launcher_resolved
from tools.apps import AppsConfigError, load_apps, open_app, save_apps
from tools.audio import get_volume, mute, set_volume, unmute
from tools.browser import open_validated_url, without_destination
from tools.capabilities import get_capabilities, get_integration_capabilities, get_mobile_capabilities
from tools.commands import (
    open_apple_music,
    open_apple_music_search,
    open_codex,
    open_league,
    open_web_search,
)
from tools.contacts import resolve_discord_contact, resolve_whatsapp_contact
from tools.control_config import (
    ControlConfigError,
    delete_whatsapp_access_token,
    get_whatsapp_access_token,
    get_whatsapp_public_status,
    set_whatsapp_settings,
    store_whatsapp_access_token,
    whatsapp_automatic_send_active,
)
from tools.diagnostics import get_self_test
from tools.discord import open_discord_app, open_discord_call, open_discord_channel
from tools.integration_catalog import (
    get_command_catalog,
    get_command_control_catalog,
    reset_command_control,
    update_command_control,
)
from tools.league import MAX_MATCH_WAIT_SECONDS, LeagueClientError, with_client, with_client_or_launch
from tools.media import send_media_action
from tools.readiness import inspect_readiness
from tools.security_policy import LOCAL_CONFIRMATION_PATHS
from tools.system import get_network_status, get_power_status, get_system_status, lock_pc, suspend_pc
from tools.text_policy import validate_bounded_text
from tools.timers import TimerManager, TimerNotFoundError, validate_timer_id
from tools.urls import validate_external_url
from tools.whatsapp import (
    open_whatsapp_chat,
    open_whatsapp_compose,
    open_whatsapp_web,
    send_whatsapp_cloud_message,
)
from trusted_unlock_devices import (
    InMemoryDeviceStore,
    WindowsRegistryDeviceStore,
    verifier_from_store,
)
from trusted_unlock_protocol import TrustedUnlockError

from backend.pipa_core.connection import (
    AUTHENTICATION_TIMEOUT_SECONDS,
    SESSION_IDLE_SECONDS,
    AuthenticatedConnection,
)
from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, parse_client_message, parse_json_object, server_message
from backend.pipa_core.tools import ToolRouter

_serial_gateway = None
_mobile_gateway = None
_uvicorn_server = None
LOGGER = logging.getLogger("pipa.agent")
MAX_REQUEST_BYTES = 16 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = 12_000
MAX_PROTOCOL_ERRORS = 5
CONTROL_UI_DIR = Path(__file__).resolve().parent / "control-ui"


def configure_logging() -> Path | None:
    """Write bounded operational logs outside the repository on Windows."""

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        logging.basicConfig(level=logging.INFO)
        return None
    try:
        log_directory = Path(local_app_data) / "Pipa" / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        log_path = log_directory / "agent.log"
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    return log_path


LOG_PATH = configure_logging()


def _serial_gateway_is_configured() -> bool:
    """Report user intent separately from whether the worker is currently alive."""

    return bool(os.environ.get("PIPA_SERIAL_PORT", "").strip())


def _serial_security_mode() -> str:
    mode = os.environ.get("PIPA_SERIAL_SECURITY", "v1").strip().lower()
    return mode or "v1"


def _serial_gateway_is_connected() -> bool:
    """Report a live COM connection, not merely a retrying worker thread."""

    return bool(_serial_gateway and _serial_gateway.connected)


def _voice_auto_confirm_enabled() -> bool:
    """Read the explicit hands-free voice setting from the user environment."""

    return os.environ.get("PIPA_VOICE_AUTO_CONFIRM", "0").strip() == "1"


def _voice_wake_phrase() -> str | None:
    """Read the explicit local wake phrase without logging its contents."""

    value = os.environ.get("PIPA_VOICE_WAKE_PHRASE", "").strip()
    if not value:
        return None
    try:
        return validate_bounded_text(value, "La frase de activación", 80).strip()
    except ValueError:
        LOGGER.error("Configured voice wake phrase is invalid; hands-free commands are gated")
        return None


def _voice_app_aliases() -> list[str]:
    """Return only current local application labels for exact voice matching."""

    try:
        apps = load_apps()
    except (AppsConfigError, OSError, ValueError):
        return []

    aliases: list[str] = []
    for app_id, app_data in apps.items():
        if isinstance(app_id, str):
            aliases.append(app_id)
        configured_aliases = app_data.get("aliases", []) if isinstance(app_data, dict) else []
        if isinstance(configured_aliases, list):
            aliases.extend(alias for alias in configured_aliases if isinstance(alias, str))
    return aliases


def _mobile_transport_mode() -> str:
    return os.environ.get("PIPA_MOBILE_TRANSPORT", "").strip().lower() or "disabled"


def _mobile_gateway_is_configured() -> bool:
    return _mobile_transport_mode() == "tcp-v2"


def _mobile_gateway_is_running() -> bool:
    return bool(_mobile_gateway and _mobile_gateway.running)


def _mobile_gateway_is_connected() -> bool:
    return bool(_mobile_gateway and _mobile_gateway.connected)


async def _read_bounded_body(request) -> bytes | None:
    """Read a request body without buffering more than the configured limit."""

    stream_reader = getattr(request, "stream", None)
    if callable(stream_reader):
        chunks: list[bytes] = []
        size = 0
        async for chunk in stream_reader():
            if not isinstance(chunk, bytes):
                return None
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                return None
            chunks.append(chunk)
        body = b"".join(chunks)
        # Starlette's BaseHTTPMiddleware replays _body to downstream handlers.
        # This assignment is only used after the complete bounded read.
        request._body = body
        return body

    body_reader = getattr(request, "body", None)
    if callable(body_reader):
        body = await body_reader()
        return body if isinstance(body, bytes) and len(body) <= MAX_REQUEST_BYTES else None
    return b""


def _harden_http_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@asynccontextmanager
async def lifespan(_app):
    global _serial_gateway, _mobile_gateway
    try:
        from pipa_serial_gateway import start_configured_gateway
        from secure_tcp_gateway import start_configured_mobile_gateway

        _serial_gateway = start_configured_gateway(pipa_core)
        _mobile_gateway = start_configured_mobile_gateway(pipa_core)
        yield
    finally:
        if _mobile_gateway is not None:
            _mobile_gateway.stop()
            _mobile_gateway = None
        if _serial_gateway is not None:
            _serial_gateway.stop()
            _serial_gateway = None


app = FastAPI(
    title="Pipα Windows Agent",
    version="0.5.0",
    lifespan=lifespan,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "[::1]"],
)


@app.exception_handler(RequestValidationError)
async def handle_request_validation(_request, _error: RequestValidationError):
    """Do not echo submitted URLs, phones or messages in 422 responses."""

    return _harden_http_response(JSONResponse(status_code=422, content={"detail": "Solicitud no válida."}))


@app.exception_handler(Exception)
async def handle_unexpected_request(_request, error: Exception):
    """Keep local configuration paths and adapter details out of HTTP errors."""

    # Keep the local log useful without recording exception text or a traceback
    # that could contain a path, URL, message or adapter payload.
    LOGGER.error("Unhandled local-agent request error: %s", type(error).__name__)
    return _harden_http_response(
        JSONResponse(status_code=500, content={"detail": "Error interno del agente."})
    )


@app.middleware("http")
async def protect_local_http(request, call_next):
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.headers.get("x-pipa-local-request") != "1"
    ):
        return _harden_http_response(
            JSONResponse(
                status_code=403,
                content={"detail": "Falta la cabecera local de Pipα."},
            )
        )
    if (
        request.method in {"POST", "PUT", "DELETE"}
        and (request.url.path in LOCAL_CONFIRMATION_PATHS or request.url.path.startswith("/control/"))
        and request.headers.get("x-pipa-local-confirmation") != "1"
    ):
        return _harden_http_response(
            JSONResponse(
                status_code=403,
                content={"detail": "Falta la confirmación local explícita de Pipα."},
            )
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return _harden_http_response(
                    JSONResponse(status_code=413, content={"detail": "Solicitud demasiado grande."})
                )
        except ValueError:
            return _harden_http_response(
                JSONResponse(status_code=400, content={"detail": "Content-Length no válido."})
            )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        body = await _read_bounded_body(request)
        if body is None:
            return _harden_http_response(
                JSONResponse(status_code=413, content={"detail": "Solicitud demasiado grande."})
            )
    response = await call_next(request)
    return _harden_http_response(response)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AppRequest(StrictRequest):
    app: str = Field(min_length=1, max_length=64)


class UrlRequest(StrictRequest):
    url: str = Field(min_length=1, max_length=2048)


class VolumeRequest(StrictRequest):
    percent: int = Field(ge=0, le=100)


class QueryRequest(StrictRequest):
    query: str = Field(min_length=1, max_length=500)


class MusicRequest(StrictRequest):
    term: str = Field(min_length=1, max_length=500)


class LeagueQueueRequest(StrictRequest):
    queue: str = Field(min_length=1, max_length=64)


class LeagueWaitRequest(StrictRequest):
    seconds: int = Field(ge=1, le=MAX_MATCH_WAIT_SECONDS)


class MediaRequest(StrictRequest):
    action: str = Field(min_length=1, max_length=32)


class TimerRequest(StrictRequest):
    seconds: int = Field(ge=1, le=24 * 60 * 60)
    label: str = Field(default="Pipα timer", min_length=1, max_length=120)


class WhatsAppRequest(StrictRequest):
    phone: str = Field(min_length=7, max_length=32)
    message: str = Field(min_length=1, max_length=4096)


class WhatsAppPhoneRequest(StrictRequest):
    phone: str = Field(min_length=7, max_length=32)


class DiscordChannelRequest(StrictRequest):
    channel_id: str = Field(min_length=17, max_length=20)
    guild_id: str | None = Field(default=None, min_length=17, max_length=20)


class ContactRequest(StrictRequest):
    contact: str = Field(min_length=1, max_length=80)


class ContactMessageRequest(ContactRequest):
    message: str = Field(min_length=1, max_length=4096)


class PipaChallengeRequest(StrictRequest):
    device_id: str = Field(min_length=1, max_length=64)


class ProcessControlRequest(StrictRequest):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    original_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )
    aliases: list[str] = Field(min_length=1, max_length=32)
    launcher: str = Field(min_length=1, max_length=1024)
    arguments: list[str] = Field(default_factory=list, max_length=31)
    enabled: bool = True


class CommandControlRequest(StrictRequest):
    enabled: bool
    phrase: str = Field(min_length=1, max_length=256)


class WhatsAppControlRequest(StrictRequest):
    automatic_send: bool
    phone_number_id: str = Field(default="", max_length=32)
    api_version: str = Field(default="v23.0", min_length=4, max_length=8)
    access_token: str | None = Field(default=None, max_length=4096)
    forget_access_token: bool = False


timer_manager = TimerManager()


def _build_pipa_core() -> PipaCore:
    if platform.system() == "Windows":
        try:
            store = WindowsRegistryDeviceStore()
            verifier = verifier_from_store(store)
        except Exception:
            # The exception may contain a local registry path or configuration
            # detail. Keep the log useful without persisting that input.
            LOGGER.error("Windows device registry unavailable; no persistent device is trusted")
            verifier = verifier_from_store(InMemoryDeviceStore())
    else:
        verifier = verifier_from_store(InMemoryDeviceStore())
    from tools.agent_catalog import build_agent_catalog

    return PipaCore(
        verifier,
        ToolRouter(build_agent_catalog(timer_manager)),
        command_catalog=get_command_catalog,
        capability_catalog=get_mobile_capabilities,
        command_catalog_authoritative=True,
        voice_auto_confirm=_voice_auto_confirm_enabled(),
        voice_wake_phrase=_voice_wake_phrase(),
        voice_app_aliases=_voice_app_aliases,
    )


pipa_core = _build_pipa_core()


@app.get("/")
def root():
    return {
        "service": "pipa-windows-agent",
        "name": "Pipα Windows Agent",
        "version": "0.5.0",
        "status": "online",
        "control_panel": "/panel",
    }


@app.get("/panel", include_in_schema=False)
def control_panel():
    return FileResponse(CONTROL_UI_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/panel/pipa-control.css", include_in_schema=False)
def control_panel_css():
    return FileResponse(CONTROL_UI_DIR / "pipa-control.css", media_type="text/css; charset=utf-8")


@app.get("/panel/pipa-control.js", include_in_schema=False)
def control_panel_js():
    return FileResponse(
        CONTROL_UI_DIR / "pipa-control.js",
        media_type="application/javascript; charset=utf-8",
    )


@app.get("/status")
def status():
    return {"success": True, "pc": "online"}


@app.post("/internal/reload")
async def api_internal_reload(request: Request):
    """Ask this exact agent to stop so the hidden launcher can replace it.

    The route is loopback-only through the HTTP middleware and needs a second
    launcher-specific header. It never starts a process and does not accept a
    target PID, which prevents the updater from having to kill an arbitrary
    listener that happens to use port 8765.
    """

    if request.headers.get("x-pipa-reload") != "1":
        raise HTTPException(status_code=403, detail="Falta la señal de recarga de Pipα.")
    if _uvicorn_server is None:
        raise HTTPException(status_code=503, detail="La recarga no está disponible.")
    loop = asyncio.get_running_loop()
    loop.call_later(0.05, setattr, _uvicorn_server, "should_exit", True)
    return {"success": True, "restarting": True}


@app.get("/capabilities")
def api_capabilities():
    return get_capabilities(
        serial_gateway_configured=_serial_gateway_is_configured(),
        serial_gateway_running=bool(_serial_gateway and _serial_gateway.running),
        serial_gateway_connected=_serial_gateway_is_connected(),
        mobile_gateway_configured=_mobile_gateway_is_configured(),
        mobile_gateway_running=_mobile_gateway_is_running(),
        mobile_gateway_connected=_mobile_gateway_is_connected(),
    )


@app.get("/integrations/status")
def api_integration_status():
    """Return only the non-sensitive integration matrix for local UIs."""

    return {"success": True, "integrations": get_integration_capabilities()}


@app.get("/readiness")
def api_readiness():
    """Return a private-data-free readiness report for the local UI."""

    return inspect_readiness()


@app.get("/commands")
def api_commands():
    """Expose safe command help for local UIs without local account data."""

    return {"success": True, "commands": get_command_catalog()}


def _control_processes() -> list[dict[str, object]]:
    apps = load_apps(include_disabled=True)
    return [
        {
            "id": app_id,
            "aliases": app_data["aliases"],
            "launcher": app_data["command"][0],
            "arguments": app_data["command"][1:],
            "enabled": app_data["enabled"],
            "launcher_resolved": launcher_resolved(app_data["command"][0]),
        }
        for app_id, app_data in sorted(apps.items(), key=lambda item: item[0].casefold())
    ]


@app.get("/control/overview")
def api_control_overview():
    """Return private local configuration only to the loopback control UI."""

    processes = _control_processes()
    commands = get_command_control_catalog()
    whatsapp = get_whatsapp_public_status()
    return {
        "success": True,
        "service": {"name": "Pipα", "version": "0.5.0", "status": "online"},
        "summary": {
            "processes": len(processes),
            "active_processes": sum(bool(process["enabled"]) for process in processes),
            "commands": len(commands),
            "active_commands": sum(bool(command["enabled"]) for command in commands),
            "automatic_whatsapp": bool(whatsapp["active"]),
        },
        "processes": processes,
        "commands": commands,
        "whatsapp": whatsapp,
    }


def _matching_app_id(apps: dict[str, object], requested: str) -> str | None:
    folded = requested.casefold()
    return next((app_id for app_id in apps if app_id.casefold() == folded), None)


@app.put("/control/processes")
def api_control_save_process(request: ProcessControlRequest):
    try:
        apps = load_apps(include_disabled=True)
        target_id = _matching_app_id(apps, request.id)
        existing_id = None
        if request.original_id is None:
            if target_id is not None:
                raise ValueError("El proceso ya existe.")
        else:
            existing_id = _matching_app_id(apps, request.original_id)
            if existing_id is None:
                raise ValueError("El proceso original ya no existe.")
            if target_id is not None and target_id != existing_id:
                raise ValueError("El proceso ya existe.")
            del apps[existing_id]
        apps[request.id] = {
            "aliases": request.aliases,
            "command": [request.launcher, *request.arguments],
            "enabled": request.enabled,
        }
        save_apps(apps)
        process = next(item for item in _control_processes() if item["id"] == request.id)
        return {"success": True, "process": process}
    except (AppsConfigError, ValueError) as error:
        raise HTTPException(status_code=400, detail="No se pudo guardar ese proceso.") from error


@app.delete("/control/processes/{app_id}")
def api_control_delete_process(app_id: str):
    try:
        apps = load_apps(include_disabled=True)
        existing_id = _matching_app_id(apps, app_id)
        if existing_id is None:
            raise ValueError("El proceso no existe.")
        del apps[existing_id]
        save_apps(apps)
        return {"success": True, "deleted": True}
    except (AppsConfigError, ValueError) as error:
        raise HTTPException(status_code=400, detail="No se pudo eliminar ese proceso.") from error


@app.post("/control/processes/{app_id}/run")
def api_control_run_process(app_id: str):
    try:
        result = open_app(app_id)
    except (AppsConfigError, ValueError) as error:
        raise HTTPException(status_code=400, detail="No se pudo ejecutar ese proceso.") from error
    if result.get("success") is not True:
        raise HTTPException(status_code=409, detail="El proceso no está disponible.")
    return result


@app.put("/control/commands/{command_id}")
def api_control_update_command(command_id: str, request: CommandControlRequest):
    try:
        command = update_command_control(command_id, enabled=request.enabled, phrase=request.phrase)
        return {"success": True, "command": command}
    except (ControlConfigError, ValueError) as error:
        raise HTTPException(status_code=400, detail="No se pudo guardar ese comando.") from error


@app.delete("/control/commands/{command_id}")
def api_control_reset_command(command_id: str):
    try:
        command = reset_command_control(command_id)
        return {"success": True, "command": command}
    except (ControlConfigError, ValueError) as error:
        raise HTTPException(status_code=400, detail="No se pudo restaurar ese comando.") from error


@app.put("/control/whatsapp")
def api_control_update_whatsapp(request: WhatsAppControlRequest):
    try:
        token = request.access_token.strip() if request.access_token else None
        if request.automatic_send and request.forget_access_token:
            raise ValueError("No se puede activar y borrar el token a la vez.")
        if request.automatic_send and not request.phone_number_id:
            raise ValueError("Falta el ID de teléfono.")
        if request.automatic_send and token is None and get_whatsapp_access_token() is None:
            raise ValueError("Falta el token.")

        set_whatsapp_settings(
            mode="cloud_api" if request.automatic_send else "manual",
            phone_number_id=request.phone_number_id,
            api_version=request.api_version,
        )
        if token is not None:
            store_whatsapp_access_token(token)
        if request.forget_access_token:
            delete_whatsapp_access_token()
        return {"success": True, "whatsapp": get_whatsapp_public_status()}
    except (ControlConfigError, ValueError) as error:
        raise HTTPException(
            status_code=400,
            detail="No se pudo guardar la automatización de WhatsApp.",
        ) from error


@app.get("/self-test")
def api_self_test():
    return get_self_test(
        serial_gateway_configured=_serial_gateway_is_configured(),
        serial_gateway_running=bool(_serial_gateway and _serial_gateway.running),
        serial_gateway_connected=_serial_gateway_is_connected(),
        mobile_gateway_configured=_mobile_gateway_is_configured(),
        mobile_gateway_running=_mobile_gateway_is_running(),
        mobile_gateway_connected=_mobile_gateway_is_connected(),
    )


@app.get("/apps")
def get_apps():
    apps = load_apps()

    return {"success": True, "apps": {app_id: app_data["aliases"] for app_id, app_data in apps.items()}}


@app.post("/open-app")
def api_open_app(request: AppRequest):
    return open_app(request.app)


@app.post("/open-url")
def api_open_url(request: UrlRequest):
    try:
        url = validate_external_url(request.url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La URL no es válida.") from error

    return without_destination(
        open_validated_url(
            url,
            browser_open=webbrowser.open,
            success_message="URL abierta en el navegador.",
            failure_message="No he podido abrir la URL en el navegador.",
        )
    )


@app.post("/web/search")
def api_web_search(request: QueryRequest):
    try:
        return open_web_search(request.query)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La búsqueda no es válida.") from error


@app.post("/music/search")
def api_music_search(request: MusicRequest):
    try:
        return open_apple_music_search(request.term)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La búsqueda musical no es válida.") from error


@app.post("/music/open")
def api_music_open():
    return without_destination(open_apple_music())


@app.post("/league/open")
def api_open_league():
    return open_league()


@app.get("/league/status")
def api_league_status():
    try:
        return with_client(lambda client: client.status())
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail="League no está disponible ahora.") from error


@app.get("/league/search/status")
def api_league_search_status():
    try:
        return with_client(lambda client: client.search_status())
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail="League no está disponible ahora.") from error


@app.post("/league/search")
def api_league_search(request: LeagueQueueRequest):
    try:
        # Keep the REST/CLI surface aligned with the authenticated device
        # tool: an explicit, confirmed matchmaking request may launch the
        # allowlisted client and wait within the adapter's hard timeout.
        return with_client_or_launch(
            lambda client: client.start_search(request.queue),
            open_league,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La cola de League no es válida.") from error
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail="League no está disponible ahora.") from error


@app.post("/league/search/wait")
def api_league_wait(request: LeagueWaitRequest):
    try:
        return with_client(lambda client: client.wait_for_match(request.seconds))
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail="League no está disponible ahora.") from error


@app.delete("/league/search")
def api_league_cancel_search():
    try:
        return with_client(lambda client: client.cancel_search())
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail="League no está disponible ahora.") from error


@app.post("/codex/open")
def api_open_codex():
    return open_codex()


@app.get("/system/status")
def api_system_status():
    return get_system_status()


@app.post("/system/lock")
def api_lock_pc():
    return lock_pc()


@app.post("/system/sleep")
def api_sleep_pc():
    return suspend_pc()


@app.get("/system/power")
def api_power_status():
    return get_power_status()


@app.get("/system/network")
def api_network_status():
    return get_network_status()


@app.post("/media/action")
def api_media_action(request: MediaRequest):
    try:
        return send_media_action(request.action)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La acción multimedia no es válida.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="El audio no está disponible ahora.") from error


@app.get("/timers")
def api_list_timers():
    return {"success": True, "timers": timer_manager.list()}


@app.post("/timers")
def api_create_timer(request: TimerRequest):
    try:
        return {"success": True, "timer": timer_manager.create(request.seconds, request.label)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El temporizador no es válido.") from error


@app.delete("/timers/{timer_id}")
def api_cancel_timer(timer_id: str):
    try:
        timer_id = validate_timer_id(timer_id)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="El identificador del temporizador no es válido."
        ) from error
    try:
        return {"success": True, "timer": timer_manager.cancel(timer_id)}
    except TimerNotFoundError as error:
        raise HTTPException(status_code=404, detail="Ese temporizador no existe.") from error


@app.post("/whatsapp/compose")
def api_whatsapp_compose(request: WhatsAppRequest):
    try:
        if whatsapp_automatic_send_active():
            return send_whatsapp_cloud_message(request.phone, request.message)
        return open_whatsapp_compose(request.phone, request.message)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="La solicitud de WhatsApp no es válida.") from error


@app.post("/whatsapp/open")
def api_whatsapp_open():
    return without_destination(open_whatsapp_web())


@app.post("/whatsapp/contact/compose")
def api_whatsapp_contact_compose(request: ContactMessageRequest):
    try:
        _contact_name, phone = resolve_whatsapp_contact(request.contact)
        if whatsapp_automatic_send_active():
            return send_whatsapp_cloud_message(phone, request.message)
        return open_whatsapp_compose(phone, request.message)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="El contacto o mensaje de WhatsApp no es válido."
        ) from error


@app.post("/whatsapp/contact/open")
def api_whatsapp_contact_open(request: ContactRequest):
    try:
        _contact_name, phone = resolve_whatsapp_contact(request.contact)
        return open_whatsapp_chat(phone)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El contacto de WhatsApp no está disponible.") from error


@app.post("/whatsapp/phone/open")
def api_whatsapp_phone_open(request: WhatsAppPhoneRequest):
    try:
        return open_whatsapp_chat(request.phone)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El teléfono de WhatsApp no es válido.") from error


@app.post("/discord/open")
def api_discord_open():
    return without_destination(open_discord_app())


@app.post("/discord/channel/open")
def api_discord_channel_open(request: DiscordChannelRequest):
    try:
        return without_destination(open_discord_channel(request.channel_id, request.guild_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El canal de Discord no es válido.") from error


@app.post("/discord/channel/call")
def api_discord_channel_call(request: DiscordChannelRequest):
    try:
        return without_destination(open_discord_call(request.channel_id, request.guild_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El canal de Discord no es válido.") from error


@app.post("/discord/contact/open")
def api_discord_contact_open(request: ContactRequest):
    try:
        _contact_name, channel_id, guild_id = resolve_discord_contact(request.contact)
        return open_discord_channel(channel_id, guild_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El contacto de Discord no está disponible.") from error


@app.post("/discord/contact/call")
def api_discord_contact_call(request: ContactRequest):
    try:
        _contact_name, channel_id, guild_id = resolve_discord_contact(request.contact)
        return open_discord_call(channel_id, guild_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="El contacto de Discord no está disponible.") from error


@app.get("/pipa/protocol")
def api_pipa_protocol():
    return {
        "success": True,
        "protocol_version": 1,
        "websocket": "/pipa/ws",
        "tool_names": pipa_core.tool_names(),
        "connected_sessions": pipa_core.sessions.count(),
        "serial_gateway_configured": _serial_gateway_is_configured(),
        "serial_gateway_running": bool(_serial_gateway and _serial_gateway.running),
        "serial_gateway_connected": _serial_gateway_is_connected(),
        "serial_gateway_security": _serial_security_mode(),
        "voice_enabled": bool(_serial_gateway and _serial_gateway.voice_enabled),
        "voice_ready": bool(_serial_gateway and _serial_gateway.voice_ready),
        "voice_local_wake_phrase_ready": bool(
            _serial_gateway and getattr(_serial_gateway, "local_wake_phrase_ready", False)
        ),
        "voice_auto_confirm": pipa_core.voice_auto_confirm,
        "voice_wake_phrase_enabled": pipa_core.voice_wake_phrase is not None,
        "mobile_transport": _mobile_transport_mode(),
        "mobile_gateway_configured": _mobile_gateway_is_configured(),
        "mobile_gateway_running": _mobile_gateway_is_running(),
        "mobile_gateway_connected": _mobile_gateway_is_connected(),
    }


@app.get("/voice/diagnostics")
def api_voice_diagnostics():
    """Expose one short-lived transcript only to the local control surface."""

    gateway = _serial_gateway
    if gateway is None:
        return {
            "success": True,
            "available": False,
            "reason": "voice_disabled",
            "voice_enabled": False,
            "voice_ready": False,
        }
    return gateway.voice_diagnostics()


@app.post("/pipa/challenge")
def api_pipa_challenge(request: PipaChallengeRequest):
    try:
        challenge = pipa_core.create_challenge(request.device_id)
    except (TrustedUnlockError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Dispositivo Pipa no emparejado.") from error
    return {"success": True, "challenge": challenge.as_dict()}


@app.websocket("/pipa/ws")
async def api_pipa_websocket(websocket: WebSocket):
    client_host = websocket.client.host if websocket.client else None
    browser_origin = websocket.headers.get("origin")
    if client_host not in {"127.0.0.1", "::1", "localhost"} or browser_origin is not None:
        await websocket.close(code=1008, reason="Pipa Core solo acepta conexiones locales por ahora")
        return

    await websocket.accept()
    connection = AuthenticatedConnection(pipa_core)
    protocol_errors = 0
    try:
        while True:
            try:
                timeout = (
                    AUTHENTICATION_TIMEOUT_SECONDS if connection.session_id is None else SESSION_IDLE_SECONDS
                )
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
                if len(raw.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                    await websocket.close(code=1009, reason="message too large")
                    return
                payload = parse_json_object(raw)
                message = parse_client_message(payload)
            except TimeoutError:
                await websocket.close(code=1001, reason="connection timeout")
                return
            except ProtocolError:
                protocol_errors += 1
                await websocket.send_json(server_message("error", code="protocol_error"))
                if protocol_errors >= MAX_PROTOCOL_ERRORS:
                    await websocket.close(code=1008, reason="too many protocol errors")
                    return
                continue

            protocol_errors = 0
            result = connection.process(message)
            for output in result.responses:
                await websocket.send_json(output)
            if result.close:
                await websocket.close(code=1008, reason="authentication failed")
                return
            if connection.idle():
                await websocket.close(code=1001, reason="connection timeout")
                return
    except WebSocketDisconnect:
        pass
    finally:
        connection.close()


@app.get("/audio/volume")
def api_get_volume():
    return get_volume()


@app.post("/audio/volume")
def api_set_volume(request: VolumeRequest):
    return set_volume(request.percent)


@app.post("/audio/mute")
def api_mute():
    return mute()


@app.post("/audio/unmute")
def api_unmute():
    return unmute()


if __name__ == "__main__":
    import uvicorn

    print("Pipa Windows Agent")
    print("Listening on http://127.0.0.1:8765")
    if LOG_PATH is not None:
        LOGGER.info("Pipa Windows Agent starting")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8765,
            ws_max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            timeout_keep_alive=5,
            access_log=False,
            log_config=None,
        )
    )
    _uvicorn_server = server
    server.run()
