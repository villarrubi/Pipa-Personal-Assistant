"""Small, allowlisted adapter for the local League Client API.

This adapter talks only to 127.0.0.1, discovers the running client token from
the current user's LeagueClientUx process, and never returns that token. The
LCU endpoints are client-internal and may change between Riot releases, so all
operations fail closed when the client is unavailable or returns an unexpected
response.
"""

from __future__ import annotations

import base64
import getpass
import http.client
import json
import ssl
from dataclasses import dataclass
from typing import Any

import psutil

QUEUE_IDS = {
    "normal_draft": 400,
    "ranked_solo": 420,
    "ranked_flex": 440,
    "aram": 450,
    "swiftplay": 490,
}
QUEUE_ALIASES = {
    "normal": "normal_draft",
    "normal draft": "normal_draft",
    "draft": "normal_draft",
    "clasificatoria": "ranked_solo",
    "clasificatoria solo": "ranked_solo",
    "solo": "ranked_solo",
    "flex": "ranked_flex",
    "ranked": "ranked_solo",
}

_ALLOWED_ENDPOINTS = {
    ("GET", "/lol-lobby/v2/lobby"),
    ("GET", "/lol-lobby/v2/lobby/matchmaking/search"),
    ("POST", "/lol-lobby/v2/lobby"),
    ("POST", "/lol-lobby/v2/lobby/matchmaking/search"),
    ("DELETE", "/lol-lobby/v2/lobby/matchmaking/search"),
}

_CLIENT_NAMES = frozenset({"leagueclientux.exe", "leagueclientux"})
_MAX_TOKEN_LENGTH = 1024


def _same_windows_user(username: object) -> bool:
    """Allow only the current user's League process when Windows exposes it."""

    if not isinstance(username, str) or not username.strip():
        # Access to another process' owner can be denied under hardened
        # Windows policies.  Do not treat that ambiguity as permission to
        # consume a command-line token from an unknown account.
        return False
    try:
        current = getpass.getuser().strip()
    except (KeyError, OSError):
        return False
    if not current:
        return False
    current_leaf = current.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    process_leaf = username.strip().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return process_leaf.casefold() == current_leaf.casefold()


class LeagueClientError(RuntimeError):
    """Expected failure while discovering or calling the League client."""


@dataclass(frozen=True)
class LeagueClientConnection:
    port: int
    token: str


def resolve_queue_id(queue: str) -> int:
    if not isinstance(queue, str):
        raise ValueError("La cola de League debe ser texto.")
    normalized = queue.strip().lower()
    normalized = QUEUE_ALIASES.get(normalized, normalized)
    if normalized not in QUEUE_IDS:
        allowed = ", ".join(sorted(QUEUE_IDS))
        raise ValueError(f"Cola no permitida. Usa una de: {allowed}.")
    return QUEUE_IDS[normalized]


def parse_client_command_line(command_line: list[str]) -> LeagueClientConnection:
    if (
        not isinstance(command_line, list)
        or not command_line
        or not all(isinstance(argument, str) for argument in command_line)
    ):
        raise LeagueClientError("La línea de comandos del cliente no es válida.")

    port_values = [
        argument.removeprefix("--app-port=")
        for argument in command_line
        if argument.startswith("--app-port=")
    ]
    token_values = [
        argument.removeprefix("--remoting-auth-token=")
        for argument in command_line
        if argument.startswith("--remoting-auth-token=")
    ]
    if len(port_values) != 1 or len(token_values) != 1:
        raise LeagueClientError("No se encontraron los parámetros seguros del cliente League.")

    port_text = port_values[0]
    token = token_values[0]
    if not port_text.isascii() or not port_text.isdigit():
        raise LeagueClientError("Los parámetros del cliente League no son válidos.")
    port = int(port_text)
    if (
        not 1 <= port <= 65535
        or not 1 <= len(token) <= _MAX_TOKEN_LENGTH
        or any(ord(char) < 0x20 or ord(char) == 0x7F or char.isspace() for char in token)
    ):
        raise LeagueClientError("Los parámetros del cliente League no son válidos.")
    return LeagueClientConnection(port=port, token=token)


def find_client_connection() -> LeagueClientConnection:
    for process in psutil.process_iter(["name", "cmdline", "username"]):
        try:
            name = (process.info.get("name") or "").lower()
            if name not in _CLIENT_NAMES or not _same_windows_user(process.info.get("username")):
                continue
            return parse_client_command_line(process.info.get("cmdline") or [])
        except (psutil.Error, ValueError, LeagueClientError):
            continue
    raise LeagueClientError("League Client no está abierto o no está listo.")


class LeagueClientApi:
    """Fixed-path client for the small matchmaking surface we expose."""

    def __init__(self, connection: LeagueClientConnection) -> None:
        self._connection = connection

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> Any:
        if (method, path) not in _ALLOWED_ENDPOINTS:
            raise LeagueClientError("Ruta League no permitida.")

        auth = base64.b64encode(f"riot:{self._connection.token}".encode()).decode("ascii")
        context = ssl._create_unverified_context()
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            self._connection.port,
            timeout=3,
            context=context,
        )
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            connection.request(
                method,
                path,
                body=payload,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read(64 * 1024)
        except OSError as error:
            raise LeagueClientError("No se pudo contactar con League Client.") from error
        finally:
            connection.close()

        if response.status in accepted_statuses:
            return None
        if response.status < 200 or response.status >= 300:
            raise LeagueClientError(f"League Client rechazó la operación ({response.status}).")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LeagueClientError("League Client devolvió una respuesta inválida.") from error

    def status(self) -> dict[str, object]:
        lobby = self._request(
            "GET",
            "/lol-lobby/v2/lobby",
            accepted_statuses=frozenset({404}),
        )
        search = self.search_status()
        return {"client": "ready", "lobby": self._safe_lobby(lobby), "search": search}

    @staticmethod
    def _safe_lobby(lobby: Any) -> dict[str, object]:
        """Expose only the fields needed by Pipα, never raw LCU lobby data."""

        if lobby is None:
            return {"present": False, "queue_id": None}
        if not isinstance(lobby, dict):
            return {"present": True, "queue_id": None}
        game_config = lobby.get("gameConfig")
        raw_queue = game_config.get("queueId") if isinstance(game_config, dict) else lobby.get("queueId")
        try:
            queue_id = int(raw_queue) if raw_queue is not None else None
        except (TypeError, ValueError):
            queue_id = None
        return {"present": True, "queue_id": queue_id}

    def search_status(self) -> dict[str, object]:
        """Read matchmaking state when the running LCU exposes that endpoint."""

        try:
            # A 404 must be treated as unsupported, not as an empty response.
            details = self._request("GET", "/lol-lobby/v2/lobby/matchmaking/search")
        except LeagueClientError:
            return {"supported": False, "searching": False, "details": None}

        searching = False
        state = "unknown"
        if isinstance(details, dict):
            state = str(details.get("searchState", details.get("state", "unknown"))).lower()
            searching = (
                state in {"searching", "inprogress", "in_progress"} or details.get("searching") is True
            )
        return {"supported": True, "searching": searching, "state": state}

    def start_search(self, queue: str) -> dict[str, object]:
        queue_id = resolve_queue_id(queue)
        current = self._request(
            "GET",
            "/lol-lobby/v2/lobby",
            accepted_statuses=frozenset({404}),
        )
        search = self.search_status()
        if search["supported"] is False:
            raise LeagueClientError(
                "La API local de matchmaking no está disponible en esta versión de League."
            )
        canonical_queue = next(name for name, identifier in QUEUE_IDS.items() if identifier == queue_id)
        if search["searching"]:
            return {
                "started": False,
                "already_searching": True,
                "queue": canonical_queue,
                "queue_id": queue_id,
            }

        if current is None:
            self._request("POST", "/lol-lobby/v2/lobby", {"queueId": queue_id})
        elif isinstance(current, dict):
            current_queue = (
                current.get("gameConfig", {}).get("queueId")
                if isinstance(current.get("gameConfig"), dict)
                else current.get("queueId")
            )
            if current_queue is None:
                raise LeagueClientError("League Client devolvió un lobby sin cola identificable.")
            try:
                current_queue_id = int(current_queue)
            except (TypeError, ValueError) as error:
                raise LeagueClientError("League Client devolvió una cola de lobby inválida.") from error
            if current_queue_id != queue_id:
                raise LeagueClientError("Ya existe un lobby de League con otra cola.")
        self._request("POST", "/lol-lobby/v2/lobby/matchmaking/search", {})
        return {"started": True, "queue": canonical_queue, "queue_id": queue_id}

    def cancel_search(self) -> dict[str, object]:
        self._request(
            "DELETE",
            "/lol-lobby/v2/lobby/matchmaking/search",
            accepted_statuses=frozenset({404}),
        )
        return {"cancelled": True}


def with_client(callback):
    connection = find_client_connection()
    return callback(LeagueClientApi(connection))
