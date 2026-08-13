# Third-party notices

## ST77916 panel driver

`src/vendor/esp_lcd_st77916.c` and `src/vendor/esp_lcd_st77916.h` are based on
the ST77916 driver published in Waveshare's official
[ESP32-S3-Touch-LCD-1.85C repository](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-1.85C).
The driver carries Espressif's Apache-2.0 SPDX notice and is adapted only for
the `esp_lcd` API shipped by the PlatformIO framework pinned by this project.

Upstream references:

- [Waveshare repository](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-1.85C)
- [Espressif ESP-IDF](https://github.com/espressif/esp-idf)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## Build platform

The PlatformIO environment pins the
[pioarduino Espressif32 platform 55.03.311](https://github.com/pioarduino/platform-espressif32/releases/tag/55.03.311)
because the official PlatformIO platform currently cannot consume the modern
Arduino-ESP32 package layout used by the QSPI `esp_lcd` API. This is a build
dependency only; it does not add a network service or runtime dependency to
the firmware.
