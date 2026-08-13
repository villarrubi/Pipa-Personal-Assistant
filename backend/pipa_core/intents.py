"""Small deterministic Spanish intent adapter used before an LLM is connected."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedIntent:
    tool_name: str
    arguments: dict[str, object]


_LEAGUE_QUEUE_ALIASES = {
    "": "normal_draft",
    "normal": "normal_draft",
    "normal draft": "normal_draft",
    "normal_draft": "normal_draft",
    "clasificatoria": "ranked_solo",
    "clasificatoria solo": "ranked_solo",
    "clasificatoria flex": "ranked_flex",
    "ranked": "ranked_solo",
    "ranked solo": "ranked_solo",
    "ranked flex": "ranked_flex",
    "solo": "ranked_solo",
    "flex": "ranked_flex",
    "aram": "aram",
    "swiftplay": "swiftplay",
}


def _fold_phrase(value: str) -> str:
    """Normalize the command grammar while preserving user arguments."""

    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _clean_music_term(value: str) -> str:
    """Remove only the natural-language connector before a music query."""

    term = value.strip()
    folded = term.casefold()
    for prefix in ("música de ", "musica de ", "de "):
        if folded.startswith(prefix):
            return term[len(prefix) :].strip()
    return term


def parse_text_intent(text: str) -> ParsedIntent | None:
    original = " ".join(text.strip().split())
    normalized = _fold_phrase(original)
    if not normalized:
        return None

    if normalized in {
        "pausa",
        "pausa la musica",
        "pausa la cancion",
        "pausa la pista",
        "continua",
        "continua la musica",
        "continua la cancion",
        "continua la pista",
        "reanuda",
        "reanuda la musica",
        "reanuda la cancion",
        "reanuda la pista",
        "reproduce",
        "reproduce la cancion",
        "reproduce la cancion seleccionada",
        "reproduce la pista",
        "reproduce la pista seleccionada",
        "reproduce la seleccion",
        "pon la cancion",
        "dale al play",
        "dale play",
    }:
        return ParsedIntent("media_action", {"action": "play_pause"})
    if normalized in {
        "para la musica",
        "para la cancion",
        "para la pista",
        "deten la musica",
        "deten la cancion",
        "deten la pista",
        "deten la reproduccion",
    }:
        return ParsedIntent("media_action", {"action": "stop"})
    if normalized in {"siguiente cancion", "siguiente"}:
        return ParsedIntent("media_action", {"action": "next"})
    if normalized in {"cancion anterior", "anterior"}:
        return ParsedIntent("media_action", {"action": "previous"})
    if normalized in {"estado del ordenador", "estado del pc", "estado del sistema"}:
        return ParsedIntent("system_status", {})
    if normalized in {
        "estado de integraciones",
        "estado de las integraciones",
        "que integraciones hay",
        "qué integraciones hay",
        "integraciones disponibles",
    }:
        return ParsedIntent("integration_status", {})
    if normalized in {"estado de bateria", "nivel de bateria", "estado de la bateria"}:
        return ParsedIntent("system_power", {})
    if normalized in {"estado de red", "estado de la red", "estado de internet"}:
        return ParsedIntent("system_network", {})
    if normalized in {"silencia el ordenador", "silencia el pc", "quita el sonido"}:
        return ParsedIntent("audio_mute", {})
    if normalized in {"activa el sonido", "activa el audio", "quita el silencio"}:
        return ParsedIntent("audio_unmute", {})
    if normalized in {"bloquea el pc", "bloquea el ordenador", "bloquear el pc"}:
        return ParsedIntent("system_lock", {})
    if normalized in {"abre discord", "abrir discord"}:
        return ParsedIntent("discord_open_app", {})
    if normalized in {"llama a discord", "llamar a discord"}:
        return ParsedIntent("discord_open_app", {})
    if normalized in {
        "abre whatsapp",
        "abrir whatsapp",
        "abre whatsapp web",
        "abrir whatsapp web",
        "abre un whatsapp",
        "abrir un whatsapp",
    }:
        return ParsedIntent("whatsapp_open", {})

    if normalized in {"abre apple music", "abrir apple music", "abre musica", "abrir musica"}:
        return ParsedIntent("music_open", {})
    if normalized in {
        "abre league",
        "abrir league",
        "abre league of legends",
        "abrir league of legends",
        "abre lol",
        "abrir lol",
    }:
        return ParsedIntent("league_open", {})
    if normalized in {"abre codex", "abrir codex"}:
        return ParsedIntent("open_codex", {})

    configured_app = re.fullmatch(
        r"(?:abre|abrir) (?:(?:la|una) )?(?:aplicaci[oó]n|app)(?: configurada)? (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if configured_app:
        return ParsedIntent("open_app", {"app": configured_app.group(1).strip()})

    whatsapp_compose = re.fullmatch(
        r"(?:prepara|abre|escribe en|manda|env[ií]a)(?: un)? whatsapp "
        r"(?:para|a) ([+\d][\d\s().-]{6,24}) "
        r"(?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_compose:
        return ParsedIntent(
            "whatsapp_compose",
            {"phone": whatsapp_compose.group(1).strip(), "message": whatsapp_compose.group(2).strip()},
        )

    whatsapp_message = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:para|a) "
        r"([+\d][\d\s().-]{6,24}) (?:por|en) whatsapp "
        r"(?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_message:
        return ParsedIntent(
            "whatsapp_compose",
            {"phone": whatsapp_message.group(1).strip(), "message": whatsapp_message.group(2).strip()},
        )

    whatsapp_message_prefix = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:por|en) whatsapp "
        r"(?:para|a) ([+\d][\d\s().-]{6,24}) "
        r"(?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_message_prefix:
        return ParsedIntent(
            "whatsapp_compose",
            {
                "phone": whatsapp_message_prefix.group(1).strip(),
                "message": whatsapp_message_prefix.group(2).strip(),
            },
        )

    whatsapp_contact_alternative = re.fullmatch(
        r"(?:prepara|abre|escribe(?:le)?|manda|env[ií]a) (?:para|a) (.+?) "
        r"(?:por|en) whatsapp (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_contact_alternative:
        return ParsedIntent(
            "whatsapp_contact",
            {
                "contact": whatsapp_contact_alternative.group(1).strip(),
                "message": whatsapp_contact_alternative.group(2).strip(),
            },
        )

    whatsapp_contact_message = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:para|a) (.+?) "
        r"(?:por|en) whatsapp (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_contact_message:
        return ParsedIntent(
            "whatsapp_contact",
            {
                "contact": whatsapp_contact_message.group(1).strip(),
                "message": whatsapp_contact_message.group(2).strip(),
            },
        )

    whatsapp_contact_message_prefix = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:por|en) whatsapp "
        r"(?:para|a) (.+?) (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_contact_message_prefix:
        return ParsedIntent(
            "whatsapp_contact",
            {
                "contact": whatsapp_contact_message_prefix.group(1).strip(),
                "message": whatsapp_contact_message_prefix.group(2).strip(),
            },
        )

    whatsapp_contact = re.fullmatch(
        r"(?:prepara|abre|escribe en|manda|env[ií]a)(?: un)? whatsapp (?:para|a|con) (.+?) "
        r"(?:y dile|y escribe|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_contact:
        return ParsedIntent(
            "whatsapp_contact",
            {"contact": whatsapp_contact.group(1).strip(), "message": whatsapp_contact.group(2).strip()},
        )

    whatsapp_chat_open = re.fullmatch(
        r"(?:abre|abrir) (?:el )?chat de (.+?) (?:en|por) whatsapp",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_chat_open:
        return ParsedIntent("whatsapp_contact_open", {"contact": whatsapp_chat_open.group(1).strip()})

    whatsapp_phone_open = re.fullmatch(
        r"(?:abre|abrir) (?:el )?whatsapp (?:para|a) ([+\d][\d\s().-]{6,24})",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_phone_open:
        return ParsedIntent("whatsapp_phone_open", {"phone": whatsapp_phone_open.group(1).strip()})

    whatsapp_contact_open = re.fullmatch(
        r"(?:abre|abrir) (?:el )?whatsapp (?:para|a) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_contact_open:
        return ParsedIntent("whatsapp_contact_open", {"contact": whatsapp_contact_open.group(1).strip()})

    discord_call_contact = re.fullmatch(
        r"(?:llama(?:r)?|haz una llamada|inicia(?:r)? una llamada|empieza(?:r)? una llamada) "
        r"(?:a|con) (?:el )?(.+?) (?:por|en) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact:
        return ParsedIntent("discord_call", {"contact": discord_call_contact.group(1).strip()})

    discord_call_contact_prefix = re.fullmatch(
        r"(?:llama(?:r)?|haz una llamada|inicia(?:r)? una llamada|empieza(?:r)? una llamada) "
        r"(?:por|en) discord (?:a|al|con) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact_prefix:
        return ParsedIntent(
            "discord_call",
            {"contact": discord_call_contact_prefix.group(1).strip()},
        )

    discord_call_server_channel_suffix = re.fullmatch(
        r"(?:llama(?:r)?|haz una llamada) (?:al|a(?:l)? )?(?:canal )?([0-9]{17,20}) "
        r"(?:del|de|en el) (?:servidor|guild) ([0-9]{17,20}) (?:por|en) discord",
        normalized,
    )
    if discord_call_server_channel_suffix:
        return ParsedIntent(
            "discord_call_channel",
            {
                "guild_id": discord_call_server_channel_suffix.group(2),
                "channel_id": discord_call_server_channel_suffix.group(1),
            },
        )

    discord_call_channel_suffix = re.fullmatch(
        r"(?:llama(?:r)?|haz una llamada) (?:al|a(?:l)? )?(?:canal )?([0-9]{17,20}) "
        r"(?:por|en) discord",
        normalized,
    )
    if discord_call_channel_suffix:
        return ParsedIntent(
            "discord_call_channel",
            {"channel_id": discord_call_channel_suffix.group(1)},
        )

    discord_open_server_channel_suffix = re.fullmatch(
        r"(?:abre|abrir) (?:el )?(?:canal )?([0-9]{17,20}) "
        r"(?:del|de|en el) (?:servidor|guild) ([0-9]{17,20}) (?:por|en) discord",
        normalized,
    )
    if discord_open_server_channel_suffix:
        return ParsedIntent(
            "discord_open",
            {
                "guild_id": discord_open_server_channel_suffix.group(2),
                "channel_id": discord_open_server_channel_suffix.group(1),
            },
        )

    discord_open_channel_suffix = re.fullmatch(
        r"(?:abre|abrir) (?:el )?(?:canal )?([0-9]{17,20}) (?:por|en) discord",
        normalized,
    )
    if discord_open_channel_suffix:
        return ParsedIntent("discord_open", {"channel_id": discord_open_channel_suffix.group(1)})

    discord_channel_contact = re.fullmatch(
        r"(?:abre|abrir) (?:el )?canal de (.+?) (?:por|en) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_channel_contact:
        return ParsedIntent("discord_contact", {"contact": discord_channel_contact.group(1).strip()})

    discord_chat_contact = re.fullmatch(
        r"(?:abre|abrir) (?:el )?chat de (.+?) (?:por|en) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_chat_contact:
        return ParsedIntent("discord_contact", {"contact": discord_chat_contact.group(1).strip()})

    discord_call_server_channel = re.fullmatch(
        r"llama(?:r)? (?:a |al )?(?:canal )?discord (?:servidor|guild) ([0-9]{17,20}) "
        r"(?:canal )?([0-9]{17,20})",
        normalized,
    )
    if discord_call_server_channel:
        return ParsedIntent(
            "discord_call_channel",
            {
                "guild_id": discord_call_server_channel.group(1),
                "channel_id": discord_call_server_channel.group(2),
            },
        )

    discord_call_channel = re.fullmatch(
        r"llama(?:r)? (?:a |al )?(?:canal )?discord (?:canal )?([0-9]{17,20})",
        normalized,
    )
    if discord_call_channel:
        return ParsedIntent("discord_call_channel", {"channel_id": discord_call_channel.group(1)})

    discord_contact = re.fullmatch(
        r"abre (?:el )?(.+?) (?:por|en) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_contact:
        return ParsedIntent("discord_contact", {"contact": discord_contact.group(1).strip()})

    discord_server_channel = re.fullmatch(
        r"(?:abre|abrir|llama a) (?:el )?discord (?:servidor|guild) ([0-9]{17,20}) "
        r"(?:canal )?([0-9]{17,20})",
        normalized,
    )
    if discord_server_channel:
        return ParsedIntent(
            "discord_open",
            {"guild_id": discord_server_channel.group(1), "channel_id": discord_server_channel.group(2)},
        )

    discord_channel = re.fullmatch(
        r"(?:abre|abrir|llama a) (?:el )?(?:canal )?discord (?:canal )?([0-9]{17,20})", normalized
    )
    if discord_channel:
        return ParsedIntent("discord_open", {"channel_id": discord_channel.group(1)})

    if re.fullmatch(
        r"cancela(?: la)? busqueda(?:(?: de(?:l)?| en el) (?:league|lol))?",
        normalized,
    ):
        return ParsedIntent("league_cancel", {})

    if normalized in {
        "estado de busqueda de league",
        "estado de busqueda de lol",
        "estado de matchmaking de league",
    }:
        return ParsedIntent("league_search_status", {})
    if normalized in {
        "estado de league",
        "estado de la partida",
        "estado de busqueda",
        "estado del matchmaking",
        "estado de matchmaking",
    }:
        return ParsedIntent("league_status", {})

    timer_list = re.fullmatch(
        r"(?:lista|muestra|ensena|enseña) (?:los )?temporizadores(?: activos)?",
        normalized,
    )
    if timer_list or normalized in {"temporizadores", "temporizadores activos"}:
        return ParsedIntent("timer_list", {})

    timer_cancel = re.fullmatch(
        r"(?:cancela|elimina) (?:el )?temporizador ([A-Za-z0-9_-]{1,32})", original, flags=re.IGNORECASE
    )
    if timer_cancel:
        return ParsedIntent("timer_cancel", {"timer_id": timer_cancel.group(1)})

    open_url = re.fullmatch(
        r"(?:abre|abrir) (?:(?:la|una) )?(?:url|enlace)(?: validada)? (https?://\S+)",
        original,
        flags=re.IGNORECASE,
    )
    if open_url:
        return ParsedIntent("open_url", {"url": open_url.group(1)})

    media_action = re.fullmatch(
        r"control multimedia (play_pause|next|previous|stop)",
        normalized,
    )
    if media_action:
        return ParsedIntent("media_action", {"action": media_action.group(1)})

    search = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar|consulta)(?: en| por)? "
        r"(?:internet|la web|web|online) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if search:
        return ParsedIntent("web_search", {"query": search.group(1).strip()})

    search_suffix = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar|consulta) (.+) "
        r"(?:en|por) (?:internet|la web|web|online)",
        original,
        flags=re.IGNORECASE,
    )
    if search_suffix:
        return ParsedIntent("web_search", {"query": search_suffix.group(1).strip()})

    music_search = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:en )?(?:apple music|música|musica) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if music_search:
        return ParsedIntent("music_search", {"term": _clean_music_term(music_search.group(1))})

    music_search_natural = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:la )?m[uú]sica (?:de )?"
        r"(.+?)(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_search_natural:
        return ParsedIntent("music_search", {"term": _clean_music_term(music_search_natural.group(1))})

    music_request = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) "
        r"(?:(?:(?:la|el|una|un) )?(?:canci[oó]n|tema)(?: de )?)?"
        r"(.+?) (?:en )?apple music",
        original,
        flags=re.IGNORECASE,
    )
    if music_request:
        return ParsedIntent("music_search", {"term": _clean_music_term(music_request.group(1))})

    music_request_natural = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) (?:la )?m[uú]sica (?:de )?"
        r"(.+?)(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_request_natural:
        return ParsedIntent("music_search", {"term": _clean_music_term(music_request_natural.group(1))})

    song_search = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:(?:la|una) )?(?:canción|cancion|tema) (?:de )?"
        r"(.+?)(?: en (?:apple music|música|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if song_search:
        return ParsedIntent("music_search", {"term": song_search.group(1).strip()})

    music_search_suffix = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (.+?) (?:en )?(?:apple music|m[uú]sica|musica)",
        original,
        flags=re.IGNORECASE,
    )
    if music_search_suffix:
        return ParsedIntent("music_search", {"term": _clean_music_term(music_search_suffix.group(1))})

    league_search = re.fullmatch(
        r"(?:(?:quiero(?: que)? )?(?:busca(?:me)?|buscar|encuentra|inicia(?:r)?|empieza(?:r)?|comienza(?:r)?|juega|jugar)) "
        r"(?:una )?(?:partida|busqueda(?: de partida)?)(?: (.+))?",
        normalized,
    )
    if league_search is None:
        league_search = re.fullmatch(
            r"(?:ponme|meteme|entra(?:r)?) en cola(?: de)?(?: (.+))?",
            normalized,
        )
    if league_search:
        queue_text = league_search.group(1) or ""
        # Accept the natural context users add when addressing the game,
        # while keeping the actual queue strictly allowlisted below.
        queue_text = re.sub(
            r"(?:^|\s+)(?:(?:en|dentro de)\s+(?:el\s+)?|(?:en el|dentro del)\s+)"
            r"(?:lol|league(?: of legends)?)$",
            "",
            queue_text,
        ).strip()
        queue_text = re.sub(r"^(?:de|en)\s+", "", queue_text).strip()
        queue = _LEAGUE_QUEUE_ALIASES.get(queue_text)
        if queue is not None:
            return ParsedIntent("league_search", {"queue": queue})

    volume = re.fullmatch(r"(?:pon|ajusta) el volumen (\d{1,3})", normalized)
    if volume:
        return ParsedIntent("audio_volume", {"percent": int(volume.group(1))})

    timer_seconds = re.fullmatch(r"(?:crea|crear) (?:un )?temporizador (\d+)", normalized)
    if timer_seconds:
        return ParsedIntent(
            "timer_create",
            {"seconds": int(timer_seconds.group(1)), "label": "Pipα timer"},
        )

    timer = re.fullmatch(r"temporizador de (\d+) minutos?", normalized)
    if timer:
        return ParsedIntent("timer_create", {"seconds": int(timer.group(1)) * 60, "label": "Pipα timer"})

    return None
