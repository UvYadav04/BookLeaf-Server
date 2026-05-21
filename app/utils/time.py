from __future__ import annotations

from datetime import datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.utcnow()


def with_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    payload.setdefault("createdAt", now)
    payload["updatedAt"] = now
    return payload
