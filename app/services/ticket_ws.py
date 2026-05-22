from __future__ import annotations

import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.utils.serialize import serialize_document

logger = logging.getLogger(__name__)
from bson import ObjectId


class TicketWebSocketManager:

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, author_id: str, websocket: WebSocket) -> None:
        author_id = str(author_id)
        await websocket.accept()
        self._connections[author_id].add(websocket)
        logger.info("Author %s connected to ticket WebSocket (%d)", author_id, len(self._connections[author_id]))

    def disconnect(self, author_id: str, websocket: WebSocket) -> None:
        author_id = str(author_id)
        self._connections[author_id].discard(websocket)
        if not self._connections[author_id]:
            del self._connections[author_id]
        logger.info("Author %s disconnected from ticket WebSocket", author_id)

    async def send_to_author(self, author_id: str, payload: dict) -> None:
        author_id = str(author_id)
        sockets = list(self._connections.get(author_id, set()))
        if not sockets:
            return

        message = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_text(message)
            except Exception:  # noqa: BLE001
                dead.append(websocket)

        for websocket in dead:
            self.disconnect(author_id, websocket)

    async def notify_ticket_update(
        self,
        db: AsyncIOMotorDatabase,
        ticket_id: str,
        *,
        event_type: str = "ticket.updated",
    ) -> None:
        ticket = await db.tickets.find_one({"_id": ObjectId(ticket_id)})
        if not ticket:
            return

        author_id = ticket.get("authorId")
        if not author_id:
            return

        updated_at = ticket.get("updatedAt")
        at = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)
        await self.send_to_author(
            author_id,
            {
                "eventType": event_type,
                "ticketId": ticket["_id"],
                "ticket": serialize_document(ticket),
                "at": at,
            },
        )


ticket_ws_manager = TicketWebSocketManager()
