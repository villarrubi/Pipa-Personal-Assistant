import asyncio
import json
import logging
import os
import platform
import sys
import webbrowser
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.apps import load_apps, open_app
from tools.audio import get_volume, mute, set_volume, unmute
from tools.commands import (
    build_apple_music_search_url,
    build_web_search_url,
    open_codex,
    open_league,
)
from tools.discord import open_discord_channel
from tools.league import LeagueClientError, with_client
from tools.media import send_media_action
from tools.system import get_network_status, get_power_status, get_system_status, lock_pc
from tools.timers import TimerManager, TimerNotFoundError
from tools.urls import validate_external_url
from tools.whatsapp import build_whatsapp_compose_url
from trusted_unlock_devices import (
    InMemoryDeviceStore,
    WindowsRegistryDeviceStore,
    verifier_from_store,
)
from trusted_unlock_protocol import TrustedUnlockError

from backend.pipa_core.connection import SESSION_IDLE_SECONDS, AuthenticatedConnection
from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, parse_client_message, server_message
from backend.pipa_core.tools import ToolRouter

_serial_gateway = None
LOGGER = logging.getLogger("pipa.agent")
MAX_REQUEST_BYTES = 16 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = 12_000
AUTHENTICATION_TIMEOUT_SECONDS = 20


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


@asynccontextmanager
async def lifespan(_app):
    global _serial_gateway
    try:
        from pipa_serial_gateway import start_configured_gateway

        _serial_gateway = start_configured_gateway(pipa_core)
        yield
    finally:
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


@app.middleware("http")
async def protect_local_http(request, call_next):
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.headers.get("x-pipa-local-request") != "1"
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "Falta la cabecera local de Pipα."},
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Solicitud demasiado grande."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Content-Length no válido."})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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


class DiscordChannelRequest(StrictRequest):
    channel_id: str = Field(min_length=17, max_length=20)
    guild_id: str | None = Field(default=None, min_length=17, max_length=20)


class PipaChallengeRequest(StrictRequest):
    device_id: str = Field(min_length=1, max_length=64)


timer_manager = TimerManager()


def _build_pipa_core() -> PipaCore:
    if platform.system() == "Windows":
        try:
            store = WindowsRegistryDeviceStore()
            verifier = verifier_from_store(store)
        except Exception:
            LOGGER.exception("Windows device registry unavailable; no persistent device is trusted")
            verifier = verifier_from_store(InMemoryDeviceStore())
    else:
        verifier = verifier_from_store(InMemoryDeviceStore())
    from tools.agent_catalog import build_agent_catalog

    return PipaCore(verifier, ToolRouter(build_agent_catalog(timer_manager)))


pipa_core = _build_pipa_core()


@app.get("/")
def root():
    return {"name": "Pipα Windows Agent", "version": "0.4.0", "status": "online"}


@app.get("/status")
def status():
    return {"success": True, "pc": "online"}


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
        raise HTTPException(status_code=400, detail=str(error)) from error

    webbrowser.open(url)

    return {"success": True, "message": f"Abriendo {url}"}


@app.post("/web/search")
def api_web_search(request: QueryRequest):
    try:
        url = build_web_search_url(request.query)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    webbrowser.open(url)
    return {"success": True, "url": url, "message": "Búsqueda abierta en el navegador."}


@app.post("/music/search")
def api_music_search(request: MusicRequest):
    try:
        url = build_apple_music_search_url(request.term)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    webbrowser.open(url)
    return {"success": True, "url": url, "message": "Búsqueda de Apple Music abierta."}


@app.post("/league/open")
def api_open_league():
    return open_league()


@app.get("/league/status")
def api_league_status():
    try:
        return with_client(lambda client: client.status())
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/league/search")
def api_league_search(request: LeagueQueueRequest):
    try:
        return with_client(lambda client: client.start_search(request.queue))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.delete("/league/search")
def api_league_cancel_search():
    try:
        return with_client(lambda client: client.cancel_search())
    except LeagueClientError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


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
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/timers")
def api_list_timers():
    return {"success": True, "timers": timer_manager.list()}


@app.post("/timers")
def api_create_timer(request: TimerRequest):
    try:
        return {"success": True, "timer": timer_manager.create(request.seconds, request.label)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/timers/{timer_id}")
def api_cancel_timer(timer_id: str):
    try:
        return {"success": True, "timer": timer_manager.cancel(timer_id)}
    except TimerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/whatsapp/compose")
def api_whatsapp_compose(request: WhatsAppRequest):
    try:
        url = build_whatsapp_compose_url(request.phone, request.message)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    webbrowser.open(url)
    return {
        "success": True,
        "url": url,
        "sent": False,
        "message": "Chat preparado; debes pulsar Enviar manualmente.",
    }


@app.post("/discord/channel/open")
def api_discord_channel_open(request: DiscordChannelRequest):
    try:
        return open_discord_channel(request.channel_id, request.guild_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/pipa/protocol")
def api_pipa_protocol():
    return {
        "success": True,
        "protocol_version": 1,
        "websocket": "/pipa/ws",
        "tool_names": pipa_core.tool_names(),
        "connected_sessions": pipa_core.sessions.count(),
        "serial_gateway_configured": _serial_gateway is not None,
        "serial_gateway_running": bool(_serial_gateway and _serial_gateway.running),
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
                payload = json.loads(raw)
                message = parse_client_message(payload)
            except TimeoutError:
                await websocket.close(code=1001, reason="connection timeout")
                return
            except (json.JSONDecodeError, ProtocolError) as error:
                await websocket.send_json(server_message("error", code="protocol_error", message=str(error)))
                continue

            result = connection.process(message)
            for output in result.responses:
                await websocket.send_json(output)
            if result.close:
                await websocket.close(code=1008, reason="authentication failed")
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
        LOGGER.info("Pipa Windows Agent starting; log=%s", LOG_PATH)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        ws_max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        timeout_keep_alive=5,
        access_log=False,
        log_config=None,
    )
