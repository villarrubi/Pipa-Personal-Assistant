from urllib.parse import urlparse

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def validate_external_url(url: str) -> str:
    """Allow only ordinary HTTP(S) URLs for the local open-url command."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("La URL no puede estar vacía.")

    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise ValueError("Solo se permiten URLs http:// o https://.")
    if not parsed.hostname:
        raise ValueError("La URL debe incluir un host.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("No se permiten credenciales incrustadas en la URL.")

    return candidate
