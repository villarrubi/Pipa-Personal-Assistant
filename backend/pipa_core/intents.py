"""Small deterministic Spanish intent adapter used before an LLM is connected."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedIntent:
    tool_name: str
    arguments: dict[str, object]


_LEAGUE_QUEUE_ALIASES = {
    "": "normal_draft",
    "normal": "normal_draft",
    "normal draft": "normal_draft",
    "normal_draft": "normal_draft",
    "draft": "normal_draft",
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


def _music_intent(value: str) -> ParsedIntent:
    """Route a music request without turning service filler into a query.

    Voice recognition often produces a request such as ``busca música en
    Apple Music`` without naming a track.  Treating ``en Apple Music`` as a
    search term is misleading and makes the UI look as if a real query was
    received.  In that case opening the configured catalogue is the useful,
    bounded action; a named artist/title remains a normal manual-selection
    search.
    """

    term = _clean_music_term(value)
    folded = _fold_phrase(term)
    if folded in {
        "",
        "musica",
        "apple music",
        "en musica",
        "en apple music",
    }:
        return ParsedIntent("music_open", {})
    return ParsedIntent("music_search", {"term": term})


def _whatsapp_recipient_intent(recipient: str, message: str) -> ParsedIntent:
    """Keep direct-phone and local-alias WhatsApp contracts distinct."""

    recipient = recipient.strip()
    if re.fullmatch(r"[+\d][\d\s().-]{6,24}", recipient):
        return ParsedIntent("whatsapp_compose", {"phone": recipient, "message": message.strip()})
    return ParsedIntent("whatsapp_contact", {"contact": recipient, "message": message.strip()})


def _league_queue_intent(queue_text: str) -> ParsedIntent | None:
    """Map natural League context to the small allowlisted queue set."""

    queue_text = queue_text.strip()
    queue_text = re.sub(
        r"(?:^|\s+)(?:(?:en|dentro de|de)\s+(?:el\s+)?|"
        r"(?:en el|dentro del|del)\s+)"
        r"(?:lol|league(?: of legends)?)$",
        "",
        queue_text,
    ).strip()
    queue_text = re.sub(r"^(?:de|en)\s+", "", queue_text).strip()
    queue = _LEAGUE_QUEUE_ALIASES.get(queue_text)
    if queue is None:
        return None
    return ParsedIntent("league_search", {"queue": queue})


def _league_wait_intent(seconds_text: str | None) -> ParsedIntent | None:
    """Build a bounded read-only matchmaking watcher intent."""

    seconds = 120 if not seconds_text else int(seconds_text)
    if not 1 <= seconds <= 300:
        return None
    return ParsedIntent("league_wait", {"seconds": seconds})


def _catalog_literal_pattern(value: str) -> str:
    """Escape visible catalog text while allowing natural whitespace runs."""

    return "".join(r"\s+" if part.isspace() else re.escape(part) for part in re.split(r"(\s+)", value))


def _catalog_value(value: str, parameter: Mapping[str, Any]) -> object | None:
    value = value.strip()
    maximum = parameter.get("max_length")
    kind = parameter.get("kind")
    options = parameter.get("options", [])
    if (
        not value
        or not isinstance(maximum, int)
        or len(value.encode("utf-8")) > maximum
        or (options and value not in options)
    ):
        return None
    if kind == "integer":
        try:
            return int(value)
        except ValueError:
            return None
    if kind == "phone" and re.fullmatch(r"[+\d][\d\s().-]{6,24}", value) is None:
        return None
    if kind in {"channel_id", "guild_id"} and re.fullmatch(r"[0-9]{17,20}", value) is None:
        return None
    if kind == "url" and re.fullmatch(r"https?://\S+", value, flags=re.IGNORECASE) is None:
        return None
    return value


def parse_catalog_intent(text: str, commands: Sequence[Mapping[str, Any]]) -> ParsedIntent | None:
    """Match an edited catalog phrase without granting a new tool capability.

    The catalog can only point at handlers already present in the router. This
    matcher turns its visible placeholders into typed arguments; the real tool
    validator still runs afterwards and remains authoritative.
    """

    original = " ".join(text.strip().split())
    if not original:
        return None
    candidates: list[tuple[int, ParsedIntent]] = []
    for command in commands:
        phrase = command.get("phrase")
        tool_name = command.get("tool_name")
        parameters = command.get("parameters", [])
        if not isinstance(phrase, str) or not isinstance(tool_name, str) or not isinstance(parameters, list):
            continue

        pieces: list[str] = []
        cursor = 0
        placeholders = list(re.finditer(r"<[^<>]+>", phrase))
        for placeholder in placeholders:
            pieces.append(_catalog_literal_pattern(phrase[cursor : placeholder.start()]))
            pieces.append(r"(.+?)")
            cursor = placeholder.end()
        pieces.append(_catalog_literal_pattern(phrase[cursor:]))
        match = re.fullmatch("".join(pieces), original, flags=re.IGNORECASE)
        if match is None or len(placeholders) != len(parameters):
            continue

        arguments: dict[str, object] = {}
        specificity = len(re.sub(r"<[^<>]+>", "", phrase))
        valid = True
        for parameter, raw_value in zip(parameters, match.groups(), strict=True):
            if not isinstance(parameter, Mapping) or not isinstance(parameter.get("name"), str):
                valid = False
                break
            value = _catalog_value(raw_value, parameter)
            if value is None:
                valid = False
                break
            arguments[parameter["name"]] = value
            if parameter.get("kind") in {"phone", "integer", "channel_id", "guild_id", "url"}:
                specificity += 50
        if not valid:
            continue
        default_arguments = command.get("default_arguments")
        if default_arguments is not None:
            if arguments or not isinstance(default_arguments, Mapping):
                continue
            arguments = dict(default_arguments)
        candidates.append((specificity, ParsedIntent(tool_name, arguments)))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


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
        "reproduce la cancion elegida",
        "reproduce el tema seleccionado",
        "pon la cancion seleccionada",
        "pon la cancion elegida",
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

    # A colon is a common voice-to-text separator: "manda un WhatsApp a
    # mamá: llego". Keep these forms local to the parser and route them to
    # the same phone/alias contracts as the longer "dile" forms above.
    whatsapp_colon_direct = re.fullmatch(
        r"(?:prepara|abre|escribe en|manda|env[ií]a)(?: un)? whatsapp "
        r"(?:para|a|con) ([^:]+?)\s*:\s*(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_colon_direct:
        return _whatsapp_recipient_intent(whatsapp_colon_direct.group(1), whatsapp_colon_direct.group(2))

    whatsapp_colon_message = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:para|a) (.+?) "
        r"(?:por|en|de) whatsapp\s*:\s*(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_colon_message:
        return _whatsapp_recipient_intent(whatsapp_colon_message.group(1), whatsapp_colon_message.group(2))

    whatsapp_colon_service = re.fullmatch(
        r"(?:prepara|abre|escribe(?:le)?|manda|env[ií]a) (?:para|a) (.+?) "
        r"(?:por|en|de) whatsapp\s*:\s*(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_colon_service:
        return _whatsapp_recipient_intent(whatsapp_colon_service.group(1), whatsapp_colon_service.group(2))

    whatsapp_message_colon = re.fullmatch(
        r"(?:prepara|abre|escribe|manda|env[ií]a)(?: un)? mensaje "
        r"(?:de|por|en) whatsapp (?:para|a) (.+?)\s*:\s*(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_message_colon:
        return _whatsapp_recipient_intent(whatsapp_message_colon.group(1), whatsapp_message_colon.group(2))

    whatsapp_open_and_write_colon = re.fullmatch(
        r"(?:abre|abrir) (?:el )?whatsapp y (?:escribe|dile) (?:a|para) "
        r"(.+?)\s*:\s*(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_open_and_write_colon:
        return _whatsapp_recipient_intent(
            whatsapp_open_and_write_colon.group(1), whatsapp_open_and_write_colon.group(2)
        )

    whatsapp_message = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:para|a) "
        r"([+\d][\d\s().-]{6,24}) (?:por|en|de) whatsapp "
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
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:por|en|de) whatsapp "
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

    # Spanish also commonly places the service before the recipient:
    # "manda un mensaje de WhatsApp a mamá". Keep the phone branch separate
    # so it continues to use the direct-phone tool contract.
    whatsapp_message_service_first_phone = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:de|por|en) whatsapp "
        r"(?:para|a) ([+\d][\d\s().-]{6,24}) "
        r"(?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_message_service_first_phone:
        return ParsedIntent(
            "whatsapp_compose",
            {
                "phone": whatsapp_message_service_first_phone.group(1).strip(),
                "message": whatsapp_message_service_first_phone.group(2).strip(),
            },
        )

    whatsapp_message_service_first_contact = re.fullmatch(
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:de|por|en) whatsapp "
        r"(?:para|a) (.+?) (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if whatsapp_message_service_first_contact:
        return ParsedIntent(
            "whatsapp_contact",
            {
                "contact": whatsapp_message_service_first_contact.group(1).strip(),
                "message": whatsapp_message_service_first_contact.group(2).strip(),
            },
        )

    whatsapp_contact_alternative = re.fullmatch(
        r"(?:prepara|abre|escribe(?:le)?|manda|env[ií]a) (?:para|a) (.+?) "
        r"(?:por|en|de) whatsapp (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
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
        r"(?:por|en|de) whatsapp (?:y dile|dile|con el mensaje|diciendo|que diga) (.+)",
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
        r"(?:manda|env[ií]a|escribe)(?: un)? mensaje (?:por|en|de) whatsapp "
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
        r"(?:(?:quiero|puedes) )?(?:llama(?:r)?|haz una llamada|inicia(?:r)? una llamada|empieza(?:r)? una llamada) "
        r"(?:a|con) (?:el )?(.+?) (?:por|en|de) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact:
        return ParsedIntent("discord_call", {"contact": discord_call_contact.group(1).strip()})

    discord_call_contact_prefix = re.fullmatch(
        r"(?:(?:quiero|puedes) )?(?:llama(?:r)?|haz una llamada|inicia(?:r)? una llamada|empieza(?:r)? una llamada) "
        r"(?:por|en|de) discord (?:a|al|con) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact_prefix:
        return ParsedIntent(
            "discord_call",
            {"contact": discord_call_contact_prefix.group(1).strip()},
        )

    discord_call_contact_service_first = re.fullmatch(
        r"(?:(?:quiero|puedes) )?(?:llama(?:r)?|haz una llamada|inicia(?:r)? una llamada|"
        r"empieza(?:r)? una llamada) a discord (?:a|al|con) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact_service_first:
        return ParsedIntent(
            "discord_call",
            {"contact": discord_call_contact_service_first.group(1).strip()},
        )

    # Voice recognition often drops "una" and adds a short courtesy suffix.
    # Keep those variants on the same manual-call boundary as the canonical
    # forms above; this route still only opens the Discord destination.
    discord_call_contact_flexible = re.fullmatch(
        r"(?:(?:quiero|puedes) )?(?:llama(?:r)?|haz una llamada|"
        r"inicia(?:r)?(?: una)? llamada|empieza(?:r)?(?: una)? llamada) "
        r"(?:a|con) (?:el )?(.+?) (?:por|en|de) discord(?: (?:ahora|por favor))?",
        original,
        flags=re.IGNORECASE,
    )
    if discord_call_contact_flexible:
        return ParsedIntent(
            "discord_call",
            {"contact": discord_call_contact_flexible.group(1).strip()},
        )

    discord_call_server_channel_suffix = re.fullmatch(
        r"(?:llama(?:r)?|haz una llamada) (?:al|a(?:l)? )?(?:canal )?([0-9]{17,20}) "
        r"(?:del|de|en el) (?:servidor|guild) ([0-9]{17,20}) (?:por|en|de) discord",
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
        r"(?:por|en|de) discord",
        normalized,
    )
    if discord_call_channel_suffix:
        return ParsedIntent(
            "discord_call_channel",
            {"channel_id": discord_call_channel_suffix.group(1)},
        )

    discord_open_server_channel_suffix = re.fullmatch(
        r"(?:abre|abrir) (?:el )?(?:canal )?([0-9]{17,20}) "
        r"(?:del|de|en el) (?:servidor|guild) ([0-9]{17,20}) (?:por|en|de) discord",
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
        r"(?:abre|abrir) (?:el )?(?:canal )?([0-9]{17,20}) (?:por|en|de) discord",
        normalized,
    )
    if discord_open_channel_suffix:
        return ParsedIntent("discord_open", {"channel_id": discord_open_channel_suffix.group(1)})

    discord_channel_contact = re.fullmatch(
        r"(?:abre|abrir) (?:el )?canal de (.+?) (?:por|en|de) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_channel_contact:
        return ParsedIntent("discord_contact", {"contact": discord_channel_contact.group(1).strip()})

    discord_chat_contact = re.fullmatch(
        r"(?:abre|abrir) (?:el )?chat de (.+?) (?:por|en|de) discord",
        original,
        flags=re.IGNORECASE,
    )
    if discord_chat_contact:
        return ParsedIntent("discord_contact", {"contact": discord_chat_contact.group(1).strip()})

    discord_contact_short = re.fullmatch(
        r"(?:abre|abrir) discord (?:a|al|con|para) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if discord_contact_short:
        return ParsedIntent("discord_contact", {"contact": discord_contact_short.group(1).strip()})

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
        r"abre (?:el )?(.+?) (?:por|en|de) discord",
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
        r"cancela(?: (?:la|el))? (?:busqueda|cola|matchmaking)"
        r"(?:(?: de(?:l)?| en el) (?:league|lol))?",
        normalized,
    ):
        return ParsedIntent("league_cancel", {})

    if re.fullmatch(
        r"estado de la cola"
        r"(?:(?: de(?:l)?| en el) (?:league|lol))?",
        normalized,
    ):
        return ParsedIntent("league_search_status", {})

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
        r"(?:internet|la web|web|online|google) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if search:
        return ParsedIntent("web_search", {"query": search.group(1).strip()})

    search_suffix = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar|consulta) (.+) "
        r"(?:en|por) (?:internet|la web|web|online|google)",
        original,
        flags=re.IGNORECASE,
    )
    if search_suffix:
        return ParsedIntent("web_search", {"query": search_suffix.group(1).strip()})

    search_subject = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar|consulta) algo (?:en|por) "
        r"(?:internet|la web|web|online|google) "
        r"(?:(?:sobre|acerca de|de) )?(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if search_subject:
        return ParsedIntent("web_search", {"query": search_subject.group(1).strip()})

    if normalized in {
        "busca musica",
        "buscar musica",
        "busca la musica",
        "buscar la musica",
        "busca una cancion",
        "buscar una cancion",
        "busca la cancion",
        "buscar la cancion",
    }:
        return ParsedIntent("music_open", {})

    music_search = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:en )?(?:apple music|música|musica) (.+)",
        original,
        flags=re.IGNORECASE,
    )
    if music_search:
        return _music_intent(music_search.group(1))

    music_search_natural = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:la )?m[uú]sica (?:de )?"
        r"(.+?)(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_search_natural:
        return _music_intent(music_search_natural.group(1))

    music_request = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) "
        r"(?:(?:(?:la|el|una|un) )?(?:canci[oó]n|tema)(?: de )?)?"
        r"(.+?) (?:en )?apple music",
        original,
        flags=re.IGNORECASE,
    )
    if music_request:
        return _music_intent(music_request.group(1))

    music_request_natural = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) (?:la )?m[uú]sica (?:de )?"
        r"(.+?)(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_request_natural:
        return _music_intent(music_request_natural.group(1))

    # When the user names the media type but omits the service, keep the same
    # safe behavior as the Apple Music form: open a bounded search and leave
    # the final track selection/playback to the person.  Requiring "canción"
    # or "tema" avoids interpreting a bare "pon X" as an external search.
    music_request_without_service = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) "
        r"(?:(?:(?:la|el|una|un) )?(?:canci[oó]n|tema)(?: de )?)"
        r"(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if music_request_without_service:
        term = _clean_music_term(music_request_without_service.group(1))
        if term.casefold() not in {"seleccionada", "seleccionado", "elegida", "elegido"}:
            return _music_intent(term)

    music_deictic = re.fullmatch(
        r"(?:pon(?:me)?|reproduce|reproducir) la de (.+?)"
        r"(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_deictic:
        term = _clean_music_term(music_deictic.group(1))
        if term.casefold() in {"seleccionada", "seleccionado", "elegida", "elegido"}:
            return ParsedIntent("media_action", {"action": "play_pause"})
        return _music_intent(term)

    music_listen = re.fullmatch(
        r"(?:quiero|me gustaría|me gustaria) escuchar "
        r"(?:(?:la|una) )?(?:(?:canci[oó]n|tema) de )?(.+?)"
        r"(?: en (?:apple music|m[uú]sica|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if music_listen:
        term = _clean_music_term(music_listen.group(1))
        if term.casefold() in {"seleccionada", "seleccionado", "elegida", "elegido"}:
            return ParsedIntent("media_action", {"action": "play_pause"})
        return _music_intent(term)

    song_search = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (?:(?:la|una) )?(?:canción|cancion|tema) (?:de )?"
        r"(.+?)(?: en (?:apple music|música|musica))?",
        original,
        flags=re.IGNORECASE,
    )
    if song_search:
        return _music_intent(song_search.group(1).strip())

    music_search_suffix = re.fullmatch(
        r"(?:b(?:u|ú)sca(?:me)?|buscar) (.+?) (?:en )?(?:apple music|m[uú]sica|musica)",
        original,
        flags=re.IGNORECASE,
    )
    if music_search_suffix:
        return _music_intent(music_search_suffix.group(1))

    league_wait = re.fullmatch(
        r"(?:espera|avisame|avisa(?:me)?) (?:a que|cuando) "
        r"(?:(?:el )?(?:league|lol) )?(?:encuentre|aparezca|salga) "
        r"(?:una )?(?:partida|match)(?: durante (\d{1,3}) segundos?)?",
        normalized,
    )
    if league_wait:
        return _league_wait_intent(league_wait.group(1))

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
    if league_search is None:
        league_search = re.fullmatch(
            r"(?:inicia|empieza|comienza) (?:el )?matchmaking(?: (?:en|de))?(?: (.+))?",
            normalized,
        )
    if league_search:
        parsed_queue = _league_queue_intent(league_search.group(1) or "")
        if parsed_queue is not None:
            return parsed_queue

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

    # User-defined processes remain inside the same application allowlist and
    # confirmation gate as the explicit "abre una aplicación" command. Keep
    # this broad fallback last so built-in integrations retain their richer,
    # typed intents.
    configured_process = re.fullmatch(
        r"(?:abre|abrir|inicia|iniciar|ejecuta|ejecutar) "
        r"(?:(?:el|la|un|una) )?(?:(?:proceso|programa|app|aplicaci[oó]n) )?(.+)",
        original,
        flags=re.IGNORECASE,
    )
    if configured_process:
        return ParsedIntent("open_app", {"app": configured_process.group(1).strip()})

    return None
