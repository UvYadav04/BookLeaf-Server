from __future__ import annotations

from datetime import datetime
from typing import Any


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return serialize_document(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def serialize_document(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            out["id"] = str(value)
            continue
        out[key] = _serialize_value(value)
    return out


def serialize_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_document(doc) for doc in docs if doc is not None]
