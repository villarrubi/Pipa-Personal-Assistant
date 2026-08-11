import webbrowser

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from tools.apps import open_app, load_apps
from tools.system import get_system_status, lock_pc
from tools.audio import get_volume, set_volume, mute, unmute
from tools.urls import validate_external_url


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


@app.get("/system/status")
def api_system_status():
    return get_system_status()


@app.post("/system/lock")
def api_lock_pc():
    return lock_pc()


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
