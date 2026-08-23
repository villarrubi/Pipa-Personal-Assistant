from pathlib import Path

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "firmware/assets/pipa_logo/pipa_logo_source.png"
TARGET = REPO_ROOT / "firmware/src/pipa_logo_asset.h"
WIDTH = 360
HEIGHT = 360
TRANSPARENT = 0x0001


def rgb565(red: int, green: int, blue: int) -> int:
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    image = ImageOps.fit(
        source,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    values = []
    for red, green, blue, alpha in image.getdata():
        values.append(TRANSPARENT if alpha < 96 else rgb565(red, green, blue))

    lines = [
        "#pragma once",
        "",
        "#include <Arduino.h>",
        "",
        "namespace pipa {",
        "",
        f"constexpr uint16_t kPipaLogoWidth = {WIDTH};",
        f"constexpr uint16_t kPipaLogoHeight = {HEIGHT};",
        f"constexpr uint16_t kPipaLogoTransparent = 0x{TRANSPARENT:04X};",
        "",
        "static const uint16_t kPipaLogoPixels[kPipaLogoWidth * kPipaLogoHeight] PROGMEM = {",
    ]
    for start in range(0, len(values), 12):
        chunk = values[start : start + 12]
        lines.append("  " + ", ".join(f"0x{value:04X}" for value in chunk) + ",")
    lines.extend(["};", "", "}  // namespace pipa", ""])
    TARGET.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
