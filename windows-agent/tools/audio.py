import comtypes
from pycaw.pycaw import AudioUtilities


def get_audio_device():
    comtypes.CoInitialize()
    return AudioUtilities.GetSpeakers()


def get_volume():
    try:
        device = get_audio_device()
        volume = device.EndpointVolume

        current = volume.GetMasterVolumeLevelScalar()
        muted = bool(volume.GetMute())

        return {
            "success": True,
            "device": device.FriendlyName,
            "volume": round(current * 100),
            "muted": muted,
        }

    finally:
        comtypes.CoUninitialize()


def set_volume(percent: int):
    percent = max(0, min(100, percent))

    try:
        device = get_audio_device()
        volume = device.EndpointVolume

        volume.SetMasterVolumeLevelScalar(percent / 100, None)

        return {"success": True, "volume": percent}

    finally:
        comtypes.CoUninitialize()


def mute():
    try:
        device = get_audio_device()
        volume = device.EndpointVolume

        volume.SetMute(1, None)

        return {"success": True, "muted": True}

    finally:
        comtypes.CoUninitialize()


def unmute():
    try:
        device = get_audio_device()
        volume = device.EndpointVolume

        volume.SetMute(0, None)

        return {"success": True, "muted": False}

    finally:
        comtypes.CoUninitialize()
