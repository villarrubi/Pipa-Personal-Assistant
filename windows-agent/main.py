import platform
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, server_message
from backend.pipa_core.tools import ToolRouter
from tools.apps import open_app, load_apps
from tools.commands import (
    build_apple_music_search_url,
    build_web_search_url,
    open_codex,
    open_league,
)
from tools.discord import open_discord_channel
from tools.league import LeagueClientError, with_client
from tools.system import get_system_status, lock_pc
from tools.system import get_network_status, get_power_status
from tools.audio import get_volume, set_volume, mute, unmute
from tools.media import send_media_action
from tools.timers import TimerManager, TimerNotFoundError
from tools.urls import validate_external_url
from tools.whatsapp import build_whatsapp_compose_url
from trusted_unlock_devices import (
    InMemoryDeviceStore,
    WindowsRegistryDeviceStore,
    verifier_from_store,
)
from trusted_unlock_protocol import TrustedUnlockError


_serial_gateway = None


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


class AppRequest(BaseModel):
    app: str


class UrlRequest(BaseModel):
    url: str


class VolumeRequest(BaseModel):
    percent: int


class QueryRequest(BaseModel):
    query: str


class MusicRequest(BaseModel):
    term: str


class LeagueQueueRequest(BaseModel):
    queue: str


class MediaRequest(BaseModel):
    action: str


class TimerRequest(BaseModel):
    seconds: int
    label: str = "Pipα timer"


class WhatsAppRequest(BaseModel):
    phone: str
    message: str


class DiscordChannelRequest(BaseModel):
    channel_id: str
    guild_id: str | None = None


class PipaChallengeRequest(BaseModel):
    device_id: str


timer_manager = TimerManager()


def _build_pipa_core() -> PipaCore:
    if platform.system() == "Windows":
        try:
            store = WindowsRegistryDeviceStore()
            verifier = verifier_from_store(store)
        except Exception:
            verifier = verifier_from_store(InMemoryDeviceStore())
    else:
        verifier = verifier_from_store(InMemoryDeviceStore())
    from tools.agent_catalog import build_agent_catalog

    return PipaCore(verifier, ToolRouter(build_agent_catalog(timer_manager)))


pipa_core = _build_pipa_core()


@app.get("/")
def root():
    return {
        "name": "Pipα Windows Agent",
        "version": "0.4.0",
        "status": "online"
    }


@app.get("/status")
def status():
    return {
        "success": True,
        "pc": "online"
    }


@app.get("/apps")
def get_apps():
    apps = load_apps()

    return {
        "success": True,
        "apps": {
            app_id: app_data["aliases"]
            for app_id, app_data in apps.items()
        }
    }


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

    return {
        "success": True,
        "message": f"Abriendo {url}"
    }


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
        "serial_gateway": _serial_gateway is not None,
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
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        await websocket.close(code=1008, reason="Pipa Core solo acepta conexiones locales por ahora")
        return

    await websocket.accept()
    session_id = None
    try:
        while True:
            payload = await websocket.receive_json()
            try:
                from backend.pipa_core.protocol import parse_client_message

                message = parse_client_message(payload)
            except ProtocolError as error:
                await websocket.send_json(server_message("error", code="protocol_error", message=str(error)))
                continue

            if session_id is None:
                if message.type != "hello":
                    await websocket.send_json(
                        server_message("error", code="authentication_required", message="Envía hello primero.")
                    )
                    continue
                try:
                    session = pipa_core.authenticate(
                        message.fields["device_id"],
                        message.fields["challenge_id"],
                        message.fields["signature"],
                    )
                except (TrustedUnlockError, ValueError) as error:
                    await websocket.send_json(
                        server_message("error", code="authentication_failed", message="Autenticación rechazada.")
                    )
                    await websocket.close(code=1008, reason="authentication failed")
                    return
                session_id = session.session_id
                await websocket.send_json(
                    server_message("ready", session_id=session_id, ui_state=session.ui_message())
                )
                continue

            if message.type == "hello":
                await websocket.send_json(server_message("error", code="already_authenticated"))
                continue
            for output in pipa_core.handle(session_id, message):
                await websocket.send_json(output)
    except WebSocketDisconnect:
        pass
    finally:
        if session_id is not None:
            pipa_core.close(session_id)


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

    print("Pipα Windows Agent")
    print("Listening on http://127.0.0.1:8765")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765
    )
