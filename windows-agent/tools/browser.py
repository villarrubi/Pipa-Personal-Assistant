"""Validated browser launching with an explicit result."""

from __future__ import annotations

from collections.abc import Callable

from tools.urls import validate_external_url


def without_destination(result: dict[str, object]) -> dict[str, object]:
    """Remove a browser destination before returning an agent/device result.

    Integrations may need the validated URL internally to launch a browser, but
    the URL can contain a search query or a private message. Keeping this
    redaction beside the browser adapter makes the boundary explicit and
    avoids each integration inventing its own response filter.
    """

    return {key: value for key, value in result.items() if key != "url"}


def open_validated_url(
    url: str,
    *,
    browser_open: Callable[[str], object],
    success_message: str,
    failure_message: str,
) -> dict[str, object]:
    """Open an HTTP(S) URL and report failure instead of assuming success."""

    validated_url = validate_external_url(url)
    try:
        opened = bool(browser_open(validated_url))
    except Exception:
        # Browser backends vary across Windows installations (for example,
        # webbrowser.Error is not an OSError). Treat every launcher failure as
        # a normal, reportable result and never expose backend details.
        opened = False

    return {
        "success": opened,
        "url": validated_url,
        "message": success_message if opened else failure_message,
    }
