import ctypes
import os
import platform
import socket
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
        "ram_available_gb": round(memory.available / (1024 ** 3), 2),
        "disk_usage": disk.percent,
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        "uptime_seconds": uptime_seconds
    }


def lock_pc():
    try:
        ctypes.windll.user32.LockWorkStation()

        return {
            "success": True,
            "message": "Orden de bloqueo enviada."
        }

    except Exception as error:
        return {
            "success": False,
            "message": "No he podido bloquear el ordenador.",
            "error": str(error)
        }