"""Optional USB-serial transport for the Waveshare device.

The gateway is deliberately opt-in. It is not an HTTP listener and it never
exposes the Windows Agent to the LAN. The device asks for a short-lived
challenge, signs it locally, and then uses the existing authenticated Pipa
Core session over newline-delimited JSON.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from backend.pipa_core.core import PipaCore
from backend.pipa_core.protocol import ProtocolError, parse_client_message, server_message
from trusted_unlock_protocol import TrustedUnlockError


LOGGER = logging.getLogger("pipa.serial")
MAX_LINE_BYTES = 12_000


class SerialGateway:
    """Serve one explicitly configured serial port in a background thread."""

    def __init__(self, core: PipaCore, port: str, *, baudrate: int = 115200) -> None:
        if not port.strip():
            raise ValueError("serial port is required")
        if baudrate < 9_600:
            raise ValueError("baudrate is too low")
        self.core = core
        self.port = port
        self.baudrate = baudrate
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipa-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            LOGGER.error("PIPA_SERIAL_PORT is configured but pyserial is not installed")
            return

        while not self._stop.is_set():
            try:
                connection = serial.Serial(self.port, self.baudrate, timeout=0.5)
            except Exception:
                LOGGER.warning("Could not open Pipa serial port %s; retrying", self.port)
                self._stop.wait(5)
                continue

            self._serve_connection(connection)

    def _serve_connection(self, connection) -> None:
        session_id: str | None = None
        try:
            with connection:
                while not self._stop.is_set():
                    raw = connection.readline()
                    if not raw:
                        continue
                    if len(raw) > MAX_LINE_BYTES:
                        self._send(connection, server_message("error", code="message_too_large"))
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                        message = parse_client_message(payload)
                        output, session_id = self._handle(message, session_id)
                    except (UnicodeDecodeError, json.JSONDecodeError, ProtocolError) as error:
                        output = [server_message("error", code="protocol_error", message=str(error))]
                    except Exception:
                        LOGGER.exception("Unexpected serial gateway error")
                        output = [server_message("error", code="internal_error")]
                    for response in output:
                        self._send(connection, response)
        except Exception:
            LOGGER.info("Pipa serial device disconnected")
        finally:
            if session_id is not None:
                self.core.close(session_id)

    def _handle(self, message, session_id: str | None) -> tuple[list[dict[str, Any]], str | None]:
        if message.type == "challenge_request":
            if session_id is not None:
                return [server_message("error", code="already_authenticated")], session_id
            try:
                challenge = self.core.create_challenge(message.fields["device_id"])
            except (TrustedUnlockError, ValueError):
                return [server_message("error", code="device_not_paired")], None
            return [server_message("challenge", challenge=challenge.as_dict())], None

        if session_id is None:
            if message.type != "hello":
                return [server_message("error", code="authentication_required")], None
            try:
                session = self.core.authenticate(
                    message.fields["device_id"],
                    message.fields["challenge_id"],
                    message.fields["signature"],
                )
            except (TrustedUnlockError, ValueError):
                return [server_message("error", code="authentication_failed")], None
            return [server_message("ready", session_id=session.session_id, ui_state=session.ui_message())], session.session_id

        if message.type in {"hello", "challenge_request"}:
            return [server_message("error", code="already_authenticated")], session_id
        return self.core.handle(session_id, message), session_id

    @staticmethod
    def _send(connection, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        connection.write(encoded)


def start_configured_gateway(core: PipaCore) -> SerialGateway | None:
    """Start the gateway only when an administrator configured its COM port."""

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
