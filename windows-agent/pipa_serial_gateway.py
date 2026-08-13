"""Authenticated USB-serial transport for a paired Pipa device.

The transport is opt-in, opens one explicitly configured serial port and never
listens on a network interface. Messages are newline-delimited UTF-8 JSON.
Human-readable device diagnostics must start with ``#`` and are ignored.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import threading
from typing import Any

from backend.pipa_core.connection import AuthenticatedConnection, ConnectionResult
from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, parse_client_message, server_message

LOGGER = logging.getLogger("pipa.serial")
MAX_LINE_BYTES = 12_000
MAX_PROTOCOL_ERRORS = 5


class SerialGateway:
    """Serve one explicitly configured serial port in a background thread."""

    def __init__(self, core: PipaCore, port: str, *, baudrate: int = 115200) -> None:
        clean_port = port.strip()
        if not clean_port or len(clean_port) > 128 or any(ord(character) < 32 for character in clean_port):
            raise ValueError("serial port is invalid")
        if platform.system() == "Windows":
            clean_port = clean_port.upper()
            if re.fullmatch(r"COM(?:[1-9][0-9]{0,2})", clean_port) is None:
                raise ValueError("serial port must be COM1 through COM999 on Windows")
        elif re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", clean_port) is None:
            raise ValueError("serial port must be an explicit /dev path")
        if not 9_600 <= baudrate <= 2_000_000:
            raise ValueError("baudrate must be between 9600 and 2000000")
        self.core = core
        self.port = clean_port
        self.baudrate = baudrate
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connected(self) -> bool:
        """Whether the worker currently owns an open serial connection."""

        return self._connected.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipa-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            LOGGER.error("PIPA_SERIAL_PORT is configured but pyserial is not installed")
            return

        warned = False
        while not self._stop.is_set():
            try:
                connection = serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=0.5,
                    write_timeout=1,
                )
                warned = False
                self._connected.set()
            except Exception:
                self._connected.clear()
                if not warned:
                    LOGGER.warning("Could not open Pipa serial port %s; retrying", self.port)
                    warned = True
                self._stop.wait(5)
                continue
            try:
                self._serve_connection(connection)
            finally:
                self._connected.clear()

    def _serve_connection(self, connection) -> None:
        protocol = AuthenticatedConnection(self.core)
        protocol_errors = 0
        try:
            with connection:
                while not self._stop.is_set() and not protocol.idle():
                    raw = connection.read_until(b"\n", MAX_LINE_BYTES + 1)
                    if not raw:
                        continue
                    if raw.startswith(b"#"):
                        continue
                    if len(raw) > MAX_LINE_BYTES:
                        connection.reset_input_buffer()
                        self._send(connection, server_message("error", code="message_too_large"))
                        protocol_errors += 1
                        if protocol_errors >= MAX_PROTOCOL_ERRORS:
                            break
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                        result = protocol.process(parse_client_message(payload))
                        protocol_errors = 0
                    except (UnicodeDecodeError, json.JSONDecodeError, ProtocolError):
                        protocol_errors += 1
                        result = ConnectionResult(
                            [server_message("error", code="protocol_error")],
                            close=protocol_errors >= MAX_PROTOCOL_ERRORS,
                        )
                    except Exception:
                        LOGGER.exception("Unexpected serial gateway error")
                        result = ConnectionResult(
                            [server_message("error", code="internal_error")], close=True
                        )

                    for response in result.responses:
                        self._send(connection, response)
                    if result.close:
                        break
        except Exception:
            LOGGER.info("Pipa serial device disconnected")
        finally:
            protocol.close()

    @staticmethod
    def _send(connection, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_LINE_BYTES:
            encoded = (
                json.dumps(
                    server_message("error", code="response_too_large"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        connection.write(encoded)


def start_configured_gateway(core: PipaCore) -> SerialGateway | None:
    """Start the gateway only when an administrator configured its COM port."""

    security_mode = os.environ.get("PIPA_SERIAL_SECURITY", "v1").strip().lower()
    if security_mode == "v2":
        from secure_serial_gateway import start_configured_secure_gateway

        return start_configured_secure_gateway(core)
    if security_mode not in {"", "v1"}:
        LOGGER.error("Unsupported PIPA_SERIAL_SECURITY mode; gateway disabled")
        return None
    port = os.environ.get("PIPA_SERIAL_PORT", "").strip()
    if not port:
        return None
    try:
        baudrate = int(os.environ.get("PIPA_SERIAL_BAUDRATE", "115200"))
        gateway = SerialGateway(core, port, baudrate=baudrate)
        gateway.start()
        LOGGER.info("Pipa USB serial gateway enabled on %s", port)
        return gateway
    except (TypeError, ValueError):
        LOGGER.exception("Invalid Pipa serial gateway configuration")
        return None
