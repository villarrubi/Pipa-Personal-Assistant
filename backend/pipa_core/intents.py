"""Small deterministic Spanish intent adapter used before an LLM is connected."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedIntent:
    tool_name: str
    arguments: dict[str, object]


def parse_text_intent(text: str) -> ParsedIntent | None:
    normalized = " ".join(text.lower().strip().split())
    if not normalized:
        return None

    if normalized in {"pausa", "pausa la música", "continúa", "continua", "reproduce"}:
        return ParsedIntent("media_action", {"action": "play_pause"})
    if normalized in {"siguiente canción", "siguiente cancion", "siguiente"}:
        return ParsedIntent("media_action", {"action": "next"})
    if normalized in {"canción anterior", "cancion anterior", "anterior"}:
        return ParsedIntent("media_action", {"action": "previous"})
    if normalized in {"bloquea el pc", "bloquea el ordenador", "bloquear el pc"}:
        return ParsedIntent("system_lock", {})
    if normalized in {"abre discord", "abrir discord"}:
        return ParsedIntent("open_app", {"app": "discord"})

    search = re.fullmatch(r"(?:busca|buscar) en internet (.+)", normalized)
    if search:
        return ParsedIntent("web_search", {"query": search.group(1)})

    volume = re.fullmatch(r"(?:pon|ajusta) el volumen (\d{1,3})", normalized)
    if volume:
        return ParsedIntent("audio_volume", {"percent": int(volume.group(1))})

    timer = re.fullmatch(r"temporizador de (\d+) minutos?", normalized)
    if timer:
        return ParsedIntent("timer_create", {"seconds": int(timer.group(1)) * 60, "label": "Pipα timer"})

    return None
