"""Attach Espressif's bounded offline speech model to hands-free uploads."""

from pathlib import Path

Import("env")  # type: ignore[name-defined]  # noqa: F821


platform = env.PioPlatform()  # type: ignore[name-defined]  # noqa: F821
libraries_dir = platform.get_package_dir("framework-arduinoespressif32-libs")
if not libraries_dir:
    raise RuntimeError("framework-arduinoespressif32-libs is unavailable")

model_path = Path(libraries_dir) / "esp32s3" / "esp_sr" / "srmodels.bin"
if not model_path.is_file():
    raise RuntimeError("the ESP-SR model image is unavailable")
if model_path.stat().st_size > 0x3E0000:
    raise RuntimeError("the ESP-SR model image exceeds the bounded model partition")

env.Append(FLASH_EXTRA_IMAGES=[("0xC10000", str(model_path))])  # type: ignore[name-defined]  # noqa: F821
