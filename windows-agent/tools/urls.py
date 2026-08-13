from urllib.parse import urlparse

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
MAX_EXTERNAL_URL_LENGTH = 2048


def validate_external_url(url: str) -> str:
    """Allow only ordinary HTTP(S) URLs for the local open-url command."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("La URL no puede estar vacía.")

    candidate = url.strip()
    if len(candidate) > MAX_EXTERNAL_URL_LENGTH:
        raise ValueError(f"La URL no puede superar {MAX_EXTERNAL_URL_LENGTH} caracteres.")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in candidate):
        raise ValueError("La URL no puede contener caracteres de control.")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise ValueError("Solo se permiten URLs http:// o https://.")
    if not parsed.hostname:
        raise ValueError("La URL debe incluir un host.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("El puerto de la URL no es válido.") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("El puerto de la URL no es válido.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("No se permiten credenciales incrustadas en la URL.")

    return candidate
