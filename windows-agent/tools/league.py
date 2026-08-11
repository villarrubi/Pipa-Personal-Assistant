"""Small, allowlisted adapter for the local League Client API.

This adapter talks only to 127.0.0.1, discovers the running client token from
the current user's LeagueClientUx process, and never returns that token. The
LCU endpoints are client-internal and may change between Riot releases, so all
operations fail closed when the client is unavailable or returns an unexpected
response.
"""

from __future__ import annotations

import base64
import http.client
import json
import re
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

_PORT_PATTERN = re.compile(r"--app-port=(\d+)")
_TOKEN_PATTERN = re.compile(r"--remoting-auth-token=([^\s]+)")
_CLIENT_NAMES = frozenset({"leagueclientux.exe", "leagueclientux"})


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
    if normalized not in QUEUE_IDS:
        allowed = ", ".join(sorted(QUEUE_IDS))
        raise ValueError(f"Cola no permitida. Usa una de: {allowed}.")
    return QUEUE_IDS[normalized]


def parse_client_command_line(command_line: list[str]) -> LeagueClientConnection:
    if not isinstance(command_line, list):
        raise LeagueClientError("La línea de comandos del cliente no es válida.")
    joined = " ".join(argument for argument in command_line if isinstance(argument, str))
    port_match = _PORT_PATTERN.search(joined)
    token_match = _TOKEN_PATTERN.search(joined)
    if port_match is None or token_match is None:
        raise LeagueClientError("No se encontraron los parámetros seguros del cliente League.")

    port = int(port_match.group(1))
    token = token_match.group(1)
    if not 1 <= port <= 65535 or not token or any(ord(char) < 0x20 for char in token):
        raise LeagueClientError("Los parámetros del cliente League no son válidos.")
    return LeagueClientConnection(port=port, token=token)


def find_client_connection() -> LeagueClientConnection:
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info.get("name") or "").lower()
            if name not in _CLIENT_NAMES:
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
        if not path.startswith("/lol-lobby/v2/"):
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
        return {"client": "ready", "lobby": lobby}

    def start_search(self, queue: str) -> dict[str, object]:
        queue_id = resolve_queue_id(queue)
        self._request("POST", "/lol-lobby/v2/lobby", {"queueId": queue_id})
        self._request("POST", "/lol-lobby/v2/lobby/matchmaking/search", {})
        return {"started": True, "queue": queue, "queue_id": queue_id}

    def cancel_search(self) -> dict[str, object]:
        self._request("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
        return {"cancelled": True}


def with_client(callback):
    connection = find_client_connection()
    return callback(LeagueClientApi(connection))
