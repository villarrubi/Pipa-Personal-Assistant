"""Shared bounds for text entering browser and messaging adapters."""

from __future__ import annotations


def validate_bounded_text(
    value: object,
    field_name: str,
    maximum_bytes: int,
    *,
    allow_line_feed: bool = False,
) -> str:
    """Validate user text without normalizing away visible content.

    Newlines are allowed only for message bodies. Bidirectional, zero-width,
    private-use and other control characters remain forbidden so previews,
    confirmations and URLs cannot be visually disguised.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} no puede estar vacío.")
    if maximum_bytes <= 0 or len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field_name} supera el límite permitido.")
    for character in value:
        code_point = ord(character)
        if (
            (code_point < 0x20 and not (allow_line_feed and code_point == 0x0A))
            or 0x7F <= code_point <= 0x9F
            or 0x200B <= code_point <= 0x200F
            or 0x202A <= code_point <= 0x202E
            or 0x2060 <= code_point <= 0x2069
            or code_point == 0xFEFF
            or 0xE000 <= code_point <= 0xF8FF
        ):
            raise ValueError(f"{field_name} contiene caracteres no permitidos.")
    return value
