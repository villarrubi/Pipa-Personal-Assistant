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
import threading
import time
from collections.abc import Callable
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
_CLIENT_START_TIMEOUT_SECONDS = 30.0
_CLIENT_START_POLL_SECONDS = 0.5
_MATCHMAKING_OPERATION_LOCK = threading.Lock()
_SEARCHING_STATES = frozenset({"searching", "inprogress", "in_progress"})
_MATCH_FOUND_STATES = frozenset(
    {
        "found",
        "match_found",
        "matchfound",
        "ready",
        "ready-check",
        "ready_check",
        "readycheck",
    }
)
_NOT_SEARCHING_STATES = frozenset(
    {
        "none",
        "idle",
        "not_searching",
        "notsearching",
        "cancelled",
        "canceled",
    }
)


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
            return {"present": False, "queue_id": None, "queue": None}
        if not isinstance(lobby, dict):
            return {"present": True, "queue_id": None, "queue": None}
        game_config = lobby.get("gameConfig")
        raw_queue = game_config.get("queueId") if isinstance(game_config, dict) else lobby.get("queueId")
        try:
            queue_id = int(raw_queue) if raw_queue is not None else None
        except (TypeError, ValueError):
            queue_id = None
        queue = next((name for name, identifier in QUEUE_IDS.items() if identifier == queue_id), None)
        return {"present": True, "queue_id": queue_id, "queue": queue}

    def search_status(self) -> dict[str, object]:
        """Read matchmaking state when the running LCU exposes that endpoint."""

        try:
            # A 404 must be treated as unsupported, not as an empty response.
            details = self._request("GET", "/lol-lobby/v2/lobby/matchmaking/search")
        except LeagueClientError:
            return {"supported": False, "searching": False, "match_found": False, "details": None}

        searching = False
        match_found = False
        state = "unknown"
        if isinstance(details, dict):
            raw_state = details.get("searchState", details.get("state", "unknown"))
            if isinstance(raw_state, str):
                normalized_state = raw_state.strip().casefold()
                if normalized_state in _SEARCHING_STATES:
                    state = "searching"
                elif normalized_state in _MATCH_FOUND_STATES:
                    state = "match_found"
                elif normalized_state in _NOT_SEARCHING_STATES:
                    state = "not_searching"
            searching = state == "searching" or details.get("searching") is True
            match_found = state == "match_found"
        return {
            "supported": True,
            "searching": searching,
            "match_found": match_found,
            "state": state,
        }

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
        if search["match_found"]:
            raise LeagueClientError("League ya encontró una partida; la aceptación debe hacerse manualmente.")
        if search["state"] == "unknown":
            # Never interpret an unfamiliar client state as idle: doing so
            # could create a second lobby or queue while the client is already
            # transitioning. A future LCU state must be mapped explicitly.
            raise LeagueClientError("No se pudo confirmar el estado actual de matchmaking.")
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
        else:
            # Do not treat an undocumented LCU response as an empty lobby.
            # Creating matchmaking from an unknown shape could act on a
            # client state that this adapter has not explicitly understood.
            raise LeagueClientError("League Client devolvió un lobby inválido.")
        self._request("POST", "/lol-lobby/v2/lobby/matchmaking/search", {})
        verification = self.search_status()
        if verification["supported"] is not True or verification["searching"] is not True:
            raise LeagueClientError("League Client no confirmó el inicio de matchmaking.")
        return {"started": True, "queue": canonical_queue, "queue_id": queue_id}

    def cancel_search(self) -> dict[str, object]:
        with _MATCHMAKING_OPERATION_LOCK:
            before = self.search_status()
            if before["supported"] is not True:
                raise LeagueClientError("La API local de matchmaking no está disponible.")
            if before["match_found"]:
                raise LeagueClientError("League ya encontró una partida; no se cancela automáticamente.")
            if before["state"] == "unknown":
                raise LeagueClientError("No se pudo confirmar el estado actual de matchmaking.")
            if before["searching"] is not True:
                return {"cancelled": False, "already_not_searching": True}

            self._request(
                "DELETE",
                "/lol-lobby/v2/lobby/matchmaking/search",
                accepted_statuses=frozenset({404}),
            )
            verification = self.search_status()
            if (
                verification["supported"] is not True
                or verification["state"] != "not_searching"
                or verification["searching"] is True
                or verification["match_found"] is True
            ):
                raise LeagueClientError("League Client no confirmó la cancelación de matchmaking.")
            return {"cancelled": True}


def with_client(callback):
    connection = find_client_connection()
    return callback(LeagueClientApi(connection))


def with_client_or_launch(
    callback: Callable[[LeagueClientApi], Any],
    launcher: Callable[[], dict[str, object]],
    *,
    timeout_seconds: float = _CLIENT_START_TIMEOUT_SECONDS,
    poll_seconds: float = _CLIENT_START_POLL_SECONDS,
) -> Any:
    """Serialize explicit matchmaking actions inside this agent process."""

    if not 0.5 <= timeout_seconds <= 120 or not 0.1 <= poll_seconds <= 5:
        raise ValueError("Los límites de espera de League no son válidos.")
    with _MATCHMAKING_OPERATION_LOCK:
        return _with_client_or_launch(
            callback,
            launcher,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )


def _with_client_or_launch(
    callback: Callable[[LeagueClientApi], Any],
    launcher: Callable[[], dict[str, object]],
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> Any:
    """Use League if ready, otherwise launch it and wait within a hard bound.

    Discovery happens before invoking ``callback`` so an LCU/API failure never
    starts a second League process. The launcher is supplied by the caller and
    is therefore still subject to the normal application allowlist and tool
    confirmation. The bounded wait only applies to the explicit matchmaking
    action; read-only status and cancellation keep their fail-closed behavior.
    """

    client_started = False
    try:
        connection = find_client_connection()
    except LeagueClientError as initial_error:
        launch_result = launcher()
        if not isinstance(launch_result, dict) or launch_result.get("success") is not True:
            raise initial_error

        client_started = True
        deadline = time.monotonic() + timeout_seconds
        connection = None
        while time.monotonic() < deadline:
            try:
                connection = find_client_connection()
                break
            except LeagueClientError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(poll_seconds, remaining))

        if connection is None:
            raise LeagueClientError(
                "League Client no estuvo listo a tiempo para buscar partida."
            ) from initial_error

    result = callback(LeagueClientApi(connection))
    if client_started and isinstance(result, dict):
        return result | {"client_started": True}
    return result
