from __future__ import annotations

from typing import Any


def event(event_type: str, **payload: Any) -> dict[str, Any]:
    """Build a realtime websocket event payload."""
    return {"type": event_type, **payload}


def error(message: str, **payload: Any) -> dict[str, Any]:
    return event("error", message=message, **payload)
