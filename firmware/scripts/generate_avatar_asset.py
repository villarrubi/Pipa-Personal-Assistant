from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "firmware/assets/pipa_avatar_ccby/Val_portrait_strip18.png"
TARGET = REPO_ROOT / "firmware/src/pipa_avatar_asset.h"
FRAME_WIDTH = 48
FRAME_HEIGHT = 48
FRAME_COUNT = 18
TRANSPARENT = 0x0001


def rgb565(red: int, green: int, blue: int) -> int:
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def main() -> None:
    image = Image.open(SOURCE).convert("RGBA")
    if image.size != (FRAME_WIDTH * FRAME_COUNT, FRAME_HEIGHT):
        raise SystemExit(f"Unexpected portrait strip size: {image.size}")

    values = []
    for frame in range(FRAME_COUNT):
        frame_values = []
        for y in range(FRAME_HEIGHT):
            for x in range(FRAME_WIDTH):
                red, green, blue, alpha = image.getpixel((frame * FRAME_WIDTH + x, y))
                frame_values.append(
                    TRANSPARENT if alpha < 128 else rgb565(red, green, blue)
                )
        values.append(frame_values)

    lines = [
        "#pragma once",
        "",
        "#include <Arduino.h>",
        "",
        "namespace pipa {",
        "",
        f"constexpr uint16_t kValPortraitFrameWidth = {FRAME_WIDTH};",
        f"constexpr uint16_t kValPortraitFrameHeight = {FRAME_HEIGHT};",
        f"constexpr uint16_t kValPortraitFrameCount = {FRAME_COUNT};",
        f"constexpr uint16_t kValPortraitTransparent = 0x{TRANSPARENT:04X};",
        "",
        "static const uint16_t kValPortraitFrames[kValPortraitFrameCount]"
        "[kValPortraitFrameWidth * kValPortraitFrameHeight] PROGMEM = {",
    ]
    for frame_values in values:
        lines.append("  {")
        for start in range(0, len(frame_values), 12):
            chunk = frame_values[start : start + 12]
            lines.append("    " + ", ".join(f"0x{value:04X}" for value in chunk) + ",")
        lines.append("  },")
    lines.extend(["};", "", "}  // namespace pipa", ""])
    TARGET.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
