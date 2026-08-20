import ctypes
import os
import platform
import socket
import threading
import time

import psutil


def get_system_status():
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")

    return {
        "success": True,
        "computer_name": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.version(),
        "cpu_usage": psutil.cpu_percent(interval=0.5),
        "ram_usage": memory.percent,
        "ram_available_gb": round(memory.available / (1024**3), 2),
        "disk_usage": disk.percent,
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "uptime_seconds": uptime_seconds,
    }


def lock_pc():
    try:
        ctypes.windll.user32.LockWorkStation()

        return {"success": True, "message": "Orden de bloqueo enviada."}

    except Exception:
        return {"success": False, "message": "No he podido bloquear el ordenador."}


def _suspend_windows() -> None:
    try:
        ctypes.windll.powrprof.SetSuspendState(False, False, False)
    except Exception:
        # This runs after the bounded success response has already been sent.
        # Never leak a platform exception from the detached callback.
        return


def suspend_pc():
    """Schedule S3 sleep after the authenticated response leaves the agent."""

    if platform.system() != "Windows":
        return {"success": False, "message": "La suspensión solo está disponible en Windows."}
    try:
        timer = threading.Timer(1.0, _suspend_windows)
        timer.daemon = True
        timer.start()
        return {"success": True, "message": "Suspensión programada."}
    except Exception:
        return {"success": False, "message": "No he podido suspender el ordenador."}


def get_power_status():
    battery = psutil.sensors_battery()
    if battery is None:
        return {"success": True, "available": False}

    seconds_left = battery.secsleft
    if seconds_left in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
        seconds_left = None
    return {
        "success": True,
        "available": True,
        "percent": battery.percent,
        "plugged": battery.power_plugged,
        "seconds_left": seconds_left,
    }


def get_network_status():
    return {
        "success": True,
        "interfaces": {
            name: {
                "is_up": stats.isup,
                "speed_mbps": stats.speed,
            }
            for name, stats in psutil.net_if_stats().items()
        },
    }
