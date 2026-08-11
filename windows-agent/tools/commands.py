"""Safe command builders for browser and application actions.

These helpers only prepare bounded, ordinary URLs or delegate to the existing
allowlisted application configuration. They do not scrape websites, control
game clients, or inject text into other applications.
"""

from __future__ import annotations

from urllib.parse import urlencode

from tools.apps import open_app
from tools.urls import validate_external_url

MAX_QUERY_LENGTH = 200
APPLE_MUSIC_STOREFRONT = "es"


def _validate_query(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} no puede estar vacío.")
    query = value.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"{field_name} no puede superar {MAX_QUERY_LENGTH} caracteres.")
    return query


def build_web_search_url(query: str) -> str:
    query = _validate_query(query, "La búsqueda")
    return validate_external_url("https://www.google.com/search?" + urlencode({"q": query}))


def build_apple_music_search_url(term: str) -> str:
    term = _validate_query(term, "La búsqueda musical")
    return validate_external_url(
        f"https://music.apple.com/{APPLE_MUSIC_STOREFRONT}/search?" + urlencode({"term": term})
    )


def open_league() -> dict[str, object]:
    """Open the configured League client; never queue or join a match."""
    return open_app("league_of_legends")


def open_codex() -> dict[str, object]:
    """Open Codex only when the user has explicitly configured its command."""
    return open_app("codex")
