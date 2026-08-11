import webbrowser

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from tools.apps import open_app, load_apps
from tools.commands import (
    build_apple_music_search_url,
    build_web_search_url,
    open_codex,
    open_league,
)
from tools.league import LeagueClientError, with_client
from tools.system import get_system_status, lock_pc
from tools.system import get_network_status, get_power_status
from tools.audio import get_volume, set_volume, mute, unmute
from tools.media import send_media_action
from tools.timers import TimerManager, TimerNotFoundError
from tools.urls import validate_external_url
from tools.whatsapp import build_whatsapp_compose_url


app = FastAPI(
    title="Pipα Windows Agent",
    version="0.3.0"
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


timer_manager = TimerManager()


@app.get("/")
def root():
    return {
        "name": "Pipα Windows Agent",
        "version": "0.3.0",
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
