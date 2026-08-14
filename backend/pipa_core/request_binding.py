"""Canonical request bindings shared by the protocol and confirmation gate."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

REQUEST_DIGEST_LENGTH = 64
_REQUEST_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def is_valid_request_digest(value: object) -> bool:
    """Return whether ``value`` is a lowercase SHA-256 hexadecimal digest."""

    return isinstance(value, str) and _REQUEST_DIGEST_PATTERN.fullmatch(value) is not None


def canonical_tool_call(name: str, arguments: Mapping[str, Any]) -> bytes:
    """Encode the small, deterministic request envelope used for binding.

    The iPhone uses Foundation JSON with sorted keys and without escaped
    slashes. Python uses the equivalent compact UTF-8 representation here.
    Catalog arguments are flat strings/integers, but rejecting non-finite or
    non-JSON values keeps this helper safe if another client calls it later.
    """

    if not isinstance(name, str) or not isinstance(arguments, Mapping):
        raise ValueError("request binding requires a tool name and object arguments")
    try:
        return json.dumps(
            {"arguments": dict(arguments), "name": name},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("request binding arguments must be JSON-serializable") from error


def compute_request_digest(name: str, arguments: Mapping[str, Any]) -> str:
    """Return the non-sensitive binding for one structured tool request."""

    return hashlib.sha256(canonical_tool_call(name, arguments)).hexdigest()
