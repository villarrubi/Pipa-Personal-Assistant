# Third-party notices

This file records the third-party code referenced directly by the firmware
source tree and `platformio.ini`. It is useful for source publication, but it
is not a substitute for a release-specific software bill of materials: the
Arduino-ESP32/ESP-IDF framework packages bring additional transitive
components and license files into a compiled image.

## ArduinoJson 7.4.3

The firmware declares `bblanchon/ArduinoJson@7.4.3` as a direct PlatformIO
dependency. Upstream source and license:

- [ArduinoJson 7.4.3](https://github.com/bblanchon/ArduinoJson/tree/v7.4.3)
- [MIT license for 7.4.3](https://github.com/bblanchon/ArduinoJson/blob/v7.4.3/LICENSE.txt)

Copyright © 2014-2026, Benoit BLANCHON

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Arduino Cryptography Library (Crypto) 0.4.0

The firmware declares `rweather/Crypto@0.4.0` as a direct PlatformIO
dependency. The upstream project states that the library is distributed under
the MIT license, and each source file carries the applicable copyright and
permission notice.

- [Arduino Cryptography Library](https://github.com/rweather/arduinolibs)
- [Upstream Crypto source](https://github.com/rweather/arduinolibs/tree/master/libraries/Crypto)

The files in version 0.4.0 carry one or more of these notices:

- Copyright (C) 2015 Southern Storm Software, Pty Ltd.
- Copyright (C) 2016 Southern Storm Software, Pty Ltd.
- Copyright (C) 2018 Southern Storm Software, Pty Ltd.
- Copyright (C) 2022 Southern Storm Software, Pty Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

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

The pinned platform currently resolves Arduino-ESP32 3.3.11 and ESP-IDF 5.5.5
framework packages. A public binary release must preserve the license and
notice files from the exact resolved packages and review the obligations of
all linked components (including LGPL-covered components). Archive that
release-specific inventory with the source revision and build provenance;
do not treat this source-level notice as an exhaustive binary-distribution
license report.
