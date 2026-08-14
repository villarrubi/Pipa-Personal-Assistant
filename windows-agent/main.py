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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.apps import load_apps, open_app
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
from tools.diagnostics import get_self_test
from tools.discord import open_discord_app, open_discord_call, open_discord_channel
from tools.integration_catalog import get_command_catalog
from tools.league import LeagueClientError, with_client, with_client_or_launch
from tools.media import send_media_action
from tools.security_policy import LOCAL_CONFIRMATION_PATHS
from tools.system import get_network_status, get_power_status, get_system_status, lock_pc
from tools.timers import TimerManager, TimerNotFoundError, validate_timer_id
from tools.urls import validate_external_url
from tools.whatsapp import open_whatsapp_chat, open_whatsapp_compose, open_whatsapp_web
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
    version="0.4.0",
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
        request.method in {"POST", "DELETE"}
        and request.url.path in LOCAL_CONFIRMATION_PATHS
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
    )


pipa_core = _build_pipa_core()


@app.get("/")
def root():
    return {
        "service": "pipa-windows-agent",
        "name": "Pipα Windows Agent",
        "version": "0.4.0",
        "status": "online",
    }


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


@app.get("/commands")
def api_commands():
    """Expose safe command help for local UIs without local account data."""

    return {"success": True, "commands": get_command_catalog()}


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
        "mobile_transport": _mobile_transport_mode(),
        "mobile_gateway_configured": _mobile_gateway_is_configured(),
        "mobile_gateway_running": _mobile_gateway_is_running(),
        "mobile_gateway_connected": _mobile_gateway_is_connected(),
    }


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
