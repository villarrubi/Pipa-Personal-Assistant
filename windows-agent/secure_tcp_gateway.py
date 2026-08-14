"""Opt-in encrypted TCP transport for the future mobile client.

The secure-session protocol already authenticates and encrypts the application
payload.  This module only supplies the outer newline-delimited transport; it
does not change the Core, add a v1 fallback, or open a listener by default.

Production configuration must provide an explicit private/loopback IP address
and port through ``PIPA_MOBILE_TRANSPORT=tcp-v2``.  Wildcard and public bind
addresses are rejected so a typo cannot expose the agent to every interface.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from secure_core_connection import SecureCoreConnection
from secure_identity_store import (
    SecureIdentityStore,
    SecureIdentityStoreError,
    default_secure_identity_path,
)
from secure_session import HandshakeError, SecureIdentity, SecureSessionError
from secure_session_server import SecureSessionServer
from trusted_unlock_devices import (
    DeviceStoreError,
    WindowsRegistryMobileDeviceStore,
)

from backend.pipa_core.connection import AUTHENTICATION_TIMEOUT_SECONDS, SESSION_IDLE_SECONDS
from backend.pipa_core.core import PipaCore

LOGGER = logging.getLogger("pipa.mobile-tcp")

MOBILE_TRANSPORT_MODE = "tcp-v2"
DEFAULT_SERVER_ID = "pipa-agent-v2"
MAX_CONNECTIONS = 4
MAX_FRAME_BYTES = 96 * 1024
DEFAULT_REVOCATION_CHECK_SECONDS = 5.0
_CLIENT_HELLO_FIELDS = frozenset(
    {
        "client_ephemeral_public_key",
        "client_id",
        "client_nonce",
        "protocol_version",
        "session_id",
        "signature",
    }
)


class SecureTcpTransportError(SecureSessionError):
    """The secure TCP transport cannot safely continue."""


def validate_mobile_bind_host(value: str) -> str:
    """Validate an explicit private or loopback IP used by the listener."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("PIPA_MOBILE_BIND must be an explicit IP address")
    host = value.strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("PIPA_MOBILE_BIND must be a literal IP address") from error
    if address.is_unspecified or address.is_multicast or (address.is_reserved and not address.is_loopback):
        raise ValueError("PIPA_MOBILE_BIND cannot be a wildcard, multicast or reserved address")
    if address.version == 6 and not address.is_loopback:
        # The current iOS client has no scoped IPv6 interface model yet. Keep
        # the server contract aligned with it until that support is designed.
        raise ValueError("PIPA_MOBILE_BIND must use IPv4 outside loopback")
    if address.version == 4:
        octets = address.packed
        is_rfc1918 = (
            octets[0] == 10
            or (octets[0] == 172 and 16 <= octets[1] <= 31)
            or (octets[0] == 192 and octets[1] == 168)
        )
        is_allowed_bind = address.is_loopback or address.is_link_local or is_rfc1918
    else:
        is_allowed_bind = address.is_loopback
    if not is_allowed_bind:
        raise ValueError("PIPA_MOBILE_BIND must be a loopback or private address")
    return host


def validate_mobile_port(value: int | str, *, allow_zero: bool = False) -> int:
    """Validate a TCP port, allowing zero only for ephemeral test listeners."""

    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("PIPA_MOBILE_PORT must be an integer") from error
    minimum = 0 if allow_zero else 1
    if not minimum <= port <= 65535:
        raise ValueError("PIPA_MOBILE_PORT must be between 1 and 65535")
    return port


def _strict_json(raw: bytes) -> dict[str, object]:
    """Parse one outer frame while rejecting duplicate fields and arrays."""

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("secure TCP frame must be an object")
    return value


def _encode_frame(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = (
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise SecureTcpTransportError("secure TCP response is not valid JSON") from error
    if len(encoded) > MAX_FRAME_BYTES:
        raise SecureTcpTransportError("secure TCP response is too large")
    return encoded


async def _read_frame(reader: asyncio.StreamReader, timeout: float) -> dict[str, object] | None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=timeout)
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise SecureTcpTransportError("secure TCP frame is incomplete") from error
    except (asyncio.LimitOverrunError, TimeoutError) as error:
        raise SecureTcpTransportError("secure TCP frame could not be read") from error
    if not raw:
        return None
    if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise SecureTcpTransportError("secure TCP frame is too large or incomplete")
    try:
        return _strict_json(raw[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SecureTcpTransportError("secure TCP frame is not valid JSON") from error


async def _write_frame(writer: asyncio.StreamWriter, payload: Mapping[str, Any]) -> None:
    writer.write(_encode_frame(payload))
    await writer.drain()


class SecureTcpGateway:
    """Serve authenticated v2 sessions on one explicitly configured IP."""

    def __init__(
        self,
        core: PipaCore,
        bind_host: str,
        port: int,
        server_identity: SecureIdentity,
        trusted_devices: Mapping[str, Any],
        *,
        max_connections: int = MAX_CONNECTIONS,
        trusted_devices_provider: Callable[[], Mapping[str, Any]] | None = None,
        revocation_check_seconds: float = DEFAULT_REVOCATION_CHECK_SECONDS,
    ) -> None:
        if not isinstance(core, PipaCore):
            raise TypeError("core must be PipaCore")
        if not isinstance(server_identity, SecureIdentity):
            raise TypeError("server_identity must be SecureIdentity")
        if not isinstance(trusted_devices, Mapping):
            raise TypeError("trusted_devices must be a mapping")
        if not 1 <= max_connections <= MAX_CONNECTIONS:
            raise ValueError("max_connections is outside the safe range")
        if trusted_devices_provider is not None and not callable(trusted_devices_provider):
            raise TypeError("trusted_devices_provider must be callable")
        if not 0.1 <= revocation_check_seconds <= 60:
            raise ValueError("revocation_check_seconds is outside the safe range")
        self.core = core
        self.bind_host = validate_mobile_bind_host(bind_host)
        self.port = validate_mobile_port(port, allow_zero=True)
        self.server_identity = server_identity
        self.trusted_devices = dict(trusted_devices)
        self.session_server = SecureSessionServer(server_identity, self.trusted_devices)
        self.max_connections = max_connections
        self.trusted_devices_provider = trusted_devices_provider
        self.revocation_check_seconds = revocation_check_seconds
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.Server | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._connections: dict[asyncio.StreamWriter, SecureCoreConnection] = {}
        self._writers_lock = threading.RLock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connected(self) -> bool:
        with self._writers_lock:
            return bool(self._writers)

    def start(self) -> None:
        """Start the listener and fail if its socket cannot be bound."""

        if self.running:
            return
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run, name="pipa-mobile-tcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            self.stop()
            raise RuntimeError("secure mobile TCP gateway did not start")
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise RuntimeError("secure mobile TCP gateway could not start") from error

    def stop(self) -> None:
        """Close the listener and all active sessions."""

        loop = self._loop
        shutdown_event = self._shutdown_event
        if loop is not None and loop.is_running() and shutdown_event is not None:
            loop.call_soon_threadsafe(self._request_shutdown)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _request_shutdown(self) -> None:
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._server is not None:
            self._server.close()
        with self._writers_lock:
            writers = tuple(self._writers)
        for writer in writers:
            writer.close()

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as error:  # pragma: no cover - startup/runtime OS failures
            self._startup_error = error
            self._ready.set()
            LOGGER.error("Secure mobile TCP gateway stopped unexpectedly")
        finally:
            self._loop = None
            self._shutdown_event = None

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.bind_host,
            port=self.port,
            limit=MAX_FRAME_BYTES + 1,
        )
        sockets = self._server.sockets or []
        if sockets:
            self.port = int(sockets[0].getsockname()[1])
        self._ready.set()
        revocation_task = None
        if self.trusted_devices_provider is not None:
            revocation_task = asyncio.create_task(self._watch_revocations())
        await self._shutdown_event.wait()
        if revocation_task is not None:
            revocation_task.cancel()
            await asyncio.gather(revocation_task, return_exceptions=True)
        self._server.close()
        await self._server.wait_closed()
        self._request_shutdown()
        with self._writers_lock:
            writers = tuple(self._writers)
        if writers:
            await asyncio.gather(*(writer.wait_closed() for writer in writers), return_exceptions=True)
        self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        secure_core = SecureCoreConnection(
            self.core,
            self.server_identity,
            self.trusted_devices,
            session_server=self.session_server,
        )
        with self._writers_lock:
            if len(self._writers) >= self.max_connections:
                writer.close()
                await writer.wait_closed()
                return
            self._writers.add(writer)
            self._connections[writer] = secure_core
        last_activity = time.monotonic()
        try:
            while True:
                idle_limit = (
                    SESSION_IDLE_SECONDS if secure_core.authenticated else AUTHENTICATION_TIMEOUT_SECONDS
                )
                remaining = idle_limit - (time.monotonic() - last_activity)
                if remaining <= 0:
                    raise SecureTcpTransportError("secure TCP connection timed out")
                payload = await _read_frame(reader, remaining)
                if payload is None:
                    return

                if not secure_core.authenticated:
                    if set(payload) != _CLIENT_HELLO_FIELDS or payload.get("protocol_version") != 2:
                        raise SecureTcpTransportError("secure TCP connection did not start with ClientHello")
                    try:
                        self._refresh_trusted_devices()
                        server_hello = secure_core.accept_client_hello(payload)
                    except (DeviceStoreError, HandshakeError, SecureSessionError, ValueError) as error:
                        raise SecureTcpTransportError("secure TCP ClientHello was rejected") from error
                    await _write_frame(writer, server_hello)
                    last_activity = time.monotonic()
                    continue

                if self.trusted_devices_provider is not None and not secure_core.device_is_trusted():
                    raise SecureTcpTransportError("secure TCP device was revoked")
                try:
                    responses = secure_core.process_frame(payload)
                except SecureSessionError as error:
                    raise SecureTcpTransportError("secure TCP encrypted frame was rejected") from error
                for response in responses:
                    await _write_frame(writer, response)
                last_activity = time.monotonic()
        except SecureTcpTransportError:
            return
        except (ConnectionError, asyncio.IncompleteReadError, OSError):
            return
        except Exception:
            LOGGER.error("Unexpected secure mobile TCP connection error")
        finally:
            secure_core.close()
            with self._writers_lock:
                self._writers.discard(writer)
                self._connections.pop(writer, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def _refresh_trusted_devices(self) -> None:
        provider = self.trusted_devices_provider
        if provider is None:
            return
        current = provider()
        if not isinstance(current, Mapping):
            raise DeviceStoreError("mobile trust provider returned an invalid mapping")
        self.session_server.refresh_trusted_devices(current)

    async def _watch_revocations(self) -> None:
        shutdown_event = self._shutdown_event
        if shutdown_event is None:
            return
        while True:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.revocation_check_seconds)
                return
            except TimeoutError:
                pass
            try:
                self._refresh_trusted_devices()
            except Exception:
                LOGGER.warning("Could not refresh mobile trust; closing active mobile sessions")
                with self._writers_lock:
                    writers = tuple(self._writers)
                for writer in writers:
                    writer.close()
                continue
            with self._writers_lock:
                active = tuple(self._connections.items())
            for writer, connection in active:
                if connection.authenticated and not connection.device_is_trusted():
                    writer.close()


def start_configured_mobile_gateway(core: PipaCore) -> SecureTcpGateway | None:
    """Start TCP only after explicit, complete, secure mobile configuration."""

    mode = os.environ.get("PIPA_MOBILE_TRANSPORT", "").strip().lower()
    if mode in {"", "disabled"}:
        return None
    if mode != MOBILE_TRANSPORT_MODE:
        LOGGER.error("Unsupported PIPA_MOBILE_TRANSPORT mode; gateway disabled")
        return None

    bind_host = os.environ.get("PIPA_MOBILE_BIND", "").strip()
    port_value = os.environ.get("PIPA_MOBILE_PORT", "").strip()
    server_id = os.environ.get("PIPA_SECURE_SERVER_ID", DEFAULT_SERVER_ID).strip()
    try:
        if not bind_host or not port_value:
            raise ValueError("PIPA_MOBILE_BIND and PIPA_MOBILE_PORT are required")
        port = validate_mobile_port(port_value)
        server_identity = SecureIdentityStore(default_secure_identity_path()).load(server_id)
        mobile_store = WindowsRegistryMobileDeviceStore()
        trusted_devices = mobile_store.trusted_public_keys()
        if not trusted_devices:
            raise DeviceStoreError("no mobile devices are paired")
        gateway = SecureTcpGateway(
            core,
            bind_host,
            port,
            server_identity,
            trusted_devices,
            trusted_devices_provider=mobile_store.trusted_public_keys,
        )
        gateway.start()
        LOGGER.info("Secure mobile TCP gateway enabled")
        return gateway
    except (DeviceStoreError, SecureIdentityStoreError, TypeError, ValueError, OSError):
        LOGGER.error("Could not configure secure mobile TCP gateway")
        return None
    except Exception:
        LOGGER.error("Could not configure secure mobile TCP gateway")
        return None
