"""Typed tool catalog and confirmation-aware invocation router."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .confirmations import ConfirmationError, ConfirmationManager

ToolHandler = Callable[[dict[str, Any]], Mapping[str, Any]]
ToolSummary = Callable[[dict[str, Any]], str]
ToolArgumentValidator = Callable[[dict[str, Any]], None]
ToolConfirmationPreparer = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    handler: ToolHandler
    safety: str = "safe"
    confirm_summary: ToolSummary | None = None
    argument_validator: ToolArgumentValidator | None = None
    confirmation_preparer: ToolConfirmationPreparer | None = None

    def __post_init__(self) -> None:
        if self.safety not in {"safe", "unsafe"}:
            raise ValueError("tool safety must be safe or unsafe")
        if self.safety == "unsafe" and self.confirm_summary is None:
            raise ValueError("unsafe tools need a confirmation summary")

    def validate_arguments(self, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        """Validate arguments before a confirmation or handler can observe them."""

        if arguments is None:
            values: dict[str, Any] = {}
        elif isinstance(arguments, Mapping):
            values = dict(arguments)
        else:
            raise ValueError("tool arguments must be an object")
        if self.argument_validator is not None:
            self.argument_validator(values)
        return values


class ToolCatalog:
    def __init__(self, definitions: list[ToolDefinition] | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {name}") from error

    def names(self) -> list[str]:
        return sorted(self._definitions)


class ToolRouter:
    def __init__(self, catalog: ToolCatalog, confirmations: ConfirmationManager | None = None) -> None:
        self.catalog = catalog
        self.confirmations = confirmations or ConfirmationManager()

    def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        confirmation_id: str | None = None,
        owner_id: str | None = None,
        call_id: str | None = None,
    ) -> dict[str, Any]:
        definition = self.catalog.get(name)
        values = definition.validate_arguments(arguments)

        if definition.safety == "unsafe" and confirmation_id is None:
            assert definition.confirm_summary is not None
            execution_arguments = None
            if definition.confirmation_preparer is not None:
                prepared = definition.confirmation_preparer(values)
                if not isinstance(prepared, Mapping):
                    raise ConfirmationError("confirmation execution arguments are invalid")
                execution_arguments = dict(prepared)
            pending = self.confirmations.create(
                name,
                values,
                definition.confirm_summary(values),
                owner_id=owner_id,
                call_id=call_id,
                execution_arguments=execution_arguments,
            )
            return {"status": "needs_confirmation", "confirmation": pending.as_dict()}

        if definition.safety == "unsafe":
            pending = self.confirmations.consume(confirmation_id or "", owner_id=owner_id)
            if pending.tool_name != name:
                raise ConfirmationError("confirmation does not match the requested tool")
            values = (
                dict(pending.execution_arguments)
                if pending.execution_arguments is not None
                else pending.arguments
            )

        return self._execute(definition, values)

    def resolve_confirmation(
        self,
        confirmation_id: str,
        accepted: bool,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        pending = self.confirmations.consume(confirmation_id, owner_id=owner_id)
        if not accepted:
            result: dict[str, Any] = {
                "status": "rejected",
                "tool_name": pending.tool_name,
                "message": "Acción cancelada por el usuario.",
            }
            if pending.call_id is not None:
                result["call_id"] = pending.call_id
            return result
        definition = self.catalog.get(pending.tool_name)
        values = (
            dict(pending.execution_arguments)
            if pending.execution_arguments is not None
            else definition.validate_arguments(pending.arguments)
        )
        result = {"tool_name": pending.tool_name, **self._execute(definition, values)}
        if pending.call_id is not None:
            result["call_id"] = pending.call_id
        return result

    def cancel_pending(self, owner_id: str) -> int:
        """Invalidate pending outward actions when a device session ends or aborts."""

        return self.confirmations.cancel_for_owner(owner_id)

    @staticmethod
    def _execute(definition: ToolDefinition, arguments: dict[str, Any]) -> dict[str, Any]:
        result = definition.handler(arguments)
        return {"status": "completed", "result": dict(result)}
