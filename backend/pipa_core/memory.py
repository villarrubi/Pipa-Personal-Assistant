"""Bounded, process-local memory for device preferences and facts."""

from __future__ import annotations

import threading
from collections import defaultdict

MAX_FACT_LENGTH = 500
MAX_FACTS_PER_DEVICE = 100
MAX_MEMORY_DEVICES = 256


class MemoryStore:
    def __init__(self) -> None:
        self._facts: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.RLock()

    def remember(self, device_id: str, fact: str) -> dict[str, object]:
        if not isinstance(fact, str) or not fact.strip() or len(fact) > MAX_FACT_LENGTH:
            raise ValueError(f"fact debe tener entre 1 y {MAX_FACT_LENGTH} caracteres")
        normalized = fact.strip()
        with self._lock:
            if device_id not in self._facts and len(self._facts) >= MAX_MEMORY_DEVICES:
                raise ValueError(f"memory only supports {MAX_MEMORY_DEVICES} devices")
            facts = self._facts[device_id]
            if normalized not in facts:
                facts.append(normalized)
            del facts[:-MAX_FACTS_PER_DEVICE]
            return {"success": True, "fact": normalized, "count": len(facts)}

    def recall(self, device_id: str) -> dict[str, object]:
        with self._lock:
            return {"success": True, "facts": list(self._facts.get(device_id, []))}
