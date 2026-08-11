"""Orchestration core for authenticated device sessions."""

from __future__ import annotations

from typing import Any

from trusted_unlock_protocol import (
    AuthorizationVerifier,
    SignedChallenge,
)

from .confirmations import ConfirmationError
from .intents import parse_text_intent
from .memory import MemoryStore
from .protocol import ClientMessage, server_message
from .state import SessionRegistry
from .tools import ToolRouter


class PipaCore:
    def __init__(
        self,
        verifier: AuthorizationVerifier,
        router: ToolRouter,
        memory: MemoryStore | None = None,
    ) -> None:
        self.verifier = verifier
        self.router = router
        self.sessions = SessionRegistry()
        self.memory = memory or MemoryStore()

    def create_challenge(self, device_id: str):
        return self.verifier.create_challenge(device_id, operation="session")

    def tool_names(self) -> list[str]:
        return sorted({*self.router.catalog.names(), "remember_fact", "recall_memory"})

    def authenticate(self, device_id: str, challenge_id: str, signature: str):
        authorization = self.verifier.verify_response(
            SignedChallenge(
                challenge_id=challenge_id,
                device_id=device_id,
                signature=signature,
            )
        )
        return self.sessions.create(authorization.device_id)

    def close(self, session_id: str) -> None:
        self.sessions.remove(session_id)

    def handle(self, session_id: str, message: ClientMessage) -> list[dict[str, Any]]:
        session = self.sessions.get(session_id)
        if session is None:
            return [server_message("error", code="unknown_session", message="Sesión desconocida.")]

        if message.type in {"wake", "hold_start"}:
            session.set_state("listening")
            return [session.ui_message()]
        if message.type in {"hold_end", "audio_end"}:
            session.set_state("thinking")
            return [session.ui_message()]
        if message.type == "abort":
            session.set_state("idle")
            return [server_message("tts_aborted"), session.ui_message()]
        if message.type == "gesture":
            return [server_message("gesture_ack", gesture=message.fields["gesture"])]
        if message.type == "text_input":
            intent = parse_text_intent(message.fields["text"])
            if intent is None:
                session.set_state("idle", caption="Todavía no conozco ese comando.")
                return [
                    server_message(
                        "error",
                        code="unsupported_text_intent",
                        message="Comando no reconocido; usa un tool_call o una frase compatible.",
                    ),
                    session.ui_message(),
                ]
            return self._run_tool(session, intent.tool_name, intent.arguments)
        if message.type == "tool_call":
            return self._run_tool(
                session,
                str(message.fields["name"]),
                message.fields["arguments"],
                call_id=message.fields.get("call_id"),
            )
        if message.type == "confirm":
            try:
                result = self.router.resolve_confirmation(
                    str(message.fields["confirmation_id"]),
                    bool(message.fields["accepted"]),
                    owner_id=session.session_id,
                )
            except (ConfirmationError, KeyError, ValueError) as error:
                return [server_message("error", code="confirmation_failed", message=str(error))]
            session.set_state("idle")
            return [server_message("tool_result", **result), session.ui_message()]

        return [server_message("error", code="unsupported_message", message=message.type)]

    def _run_tool(
        self,
        session,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str | None = None,
    ) -> list[dict[str, Any]]:
        session.set_state("thinking")
        if tool_name == "remember_fact":
            try:
                result = self.memory.remember(session.device_id, str(arguments.get("fact", "")))
            except ValueError as error:
                return [server_message("error", code="memory_failed", message=str(error)), session.ui_message()]
            session.set_state("idle")
            return [server_message("tool_result", status="completed", result=result), session.ui_message()]
        if tool_name == "recall_memory":
            session.set_state("idle")
            return [
                server_message("tool_result", status="completed", result=self.memory.recall(session.device_id)),
                session.ui_message(),
            ]
        try:
            invocation = self.router.invoke(tool_name, arguments, owner_id=session.session_id)
        except (KeyError, ValueError, ConfirmationError):
            session.set_state("idle", caption="No he podido ejecutar esa acción.")
            return [
                server_message("error", code="tool_failed", message="No he podido ejecutar esa acción."),
                session.ui_message(),
            ]
        except Exception:
            session.set_state("idle", caption="La herramienta ha fallado.")
            return [
                server_message("error", code="tool_failed", message="La herramienta ha fallado."),
                session.ui_message(),
            ]

        if invocation["status"] == "needs_confirmation":
            session.set_state("confirm")
            confirmation = invocation["confirmation"]
            return [
                server_message(
                    "confirm_request",
                    confirmation_id=confirmation["confirmation_id"],
                    tool_name=confirmation["tool_name"],
                    summary=confirmation["summary"],
                    expires_at=confirmation["expires_at"],
                ),
                session.ui_message(),
            ]

        session.set_state("idle")
        return [
            server_message("tool_result", call_id=call_id, **invocation),
            session.ui_message(),
        ]
