"""Safe command builders for browser and application actions.

These helpers only prepare bounded, ordinary URLs or delegate to the existing
allowlisted application configuration. They do not scrape websites, control
game clients, or inject text into other applications.
"""

from __future__ import annotations

import webbrowser
from urllib.parse import urlencode

from tools.apps import AppsConfigError, open_app
from tools.browser import open_validated_url, without_destination
from tools.text_policy import validate_bounded_text
from tools.urls import validate_external_url

MAX_QUERY_LENGTH = 200
APPLE_MUSIC_STOREFRONT = "es"
APPLE_MUSIC_BROWSE_URL = f"https://music.apple.com/{APPLE_MUSIC_STOREFRONT}/browse"


def _validate_query(value: str, field_name: str) -> str:
    query = validate_bounded_text(value, field_name, MAX_QUERY_LENGTH)
    return query.strip()


def build_web_search_url(query: str) -> str:
    query = _validate_query(query, "La búsqueda")
    return validate_external_url("https://www.google.com/search?" + urlencode({"q": query}))


def open_web_search(query: str) -> dict[str, object]:
    """Open a bounded web search and keep its destination out of results."""

    return without_destination(
        open_validated_url(
            build_web_search_url(query),
            browser_open=webbrowser.open,
            success_message="Búsqueda abierta en el navegador.",
            failure_message="No he podido abrir la búsqueda en el navegador.",
        )
    )


def build_apple_music_search_url(term: str) -> str:
    term = _validate_query(term, "La búsqueda musical")
    return validate_external_url(
        f"https://music.apple.com/{APPLE_MUSIC_STOREFRONT}/search?" + urlencode({"term": term})
    )


def open_apple_music_search(term: str) -> dict[str, object]:
    """Open Apple Music search without selecting or starting playback."""

    return without_destination(
        open_validated_url(
            build_apple_music_search_url(term),
            browser_open=webbrowser.open,
            success_message="Búsqueda de Apple Music abierta; elige la canción manualmente.",
            failure_message="No he podido abrir la búsqueda de Apple Music.",
        )
    ) | {"playback_started": False, "requires_manual_selection": True}


def build_apple_music_browse_url() -> str:
    """Return the fixed Apple Music catalogue URL for the configured storefront."""

    return validate_external_url(APPLE_MUSIC_BROWSE_URL)


def open_apple_music() -> dict[str, object]:
    """Open the configured Apple Music app, falling back to its web catalogue."""

    try:
        result = open_app("apple_music")
    except AppsConfigError:
        # A damaged or absent local allowlist must not turn a safe web fallback
        # into an internal error. The fallback remains a fixed, validated URL.
        result = {"success": False}
    if result.get("success"):
        return {
            **result,
            "target": "desktop_app",
            "playback_started": False,
            "requires_manual_selection": True,
        }

    url = build_apple_music_browse_url()
    opened = open_validated_url(
        url,
        browser_open=webbrowser.open,
        success_message="Apple Music no está configurado como app; he abierto su catálogo web.",
        failure_message="No he podido abrir Apple Music ni su catálogo web.",
    )
    return {
        **without_destination(opened),
        "target": "web",
        "playback_started": False,
        "requires_manual_selection": True,
    }


def open_league() -> dict[str, object]:
    """Open the configured League client; never queue or join a match."""
    return open_app("league_of_legends")


def open_codex() -> dict[str, object]:
    """Open Codex only when the user has explicitly configured its command."""
    return open_app("codex")
