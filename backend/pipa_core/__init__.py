"""Device protocol and orchestration core for Pipα."""

from .compat import ensure_windows_agent_importable

ensure_windows_agent_importable()

from .core import PipaCore
from .memory import MemoryStore
from .protocol import PROTOCOL_VERSION, ProtocolError, parse_client_message
from .tools import ToolCatalog, ToolDefinition, ToolRouter

__all__ = [
    "PipaCore",
    "MemoryStore",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "ToolCatalog",
    "ToolDefinition",
    "ToolRouter",
    "parse_client_message",
]
