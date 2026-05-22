from __future__ import annotations

import asyncio
import logging
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.qdrant import ticket_vectors
from app.schemas.ticket import AdminTicketUpdateRequest, TicketCreateRequest
from app.services.ai_service import ai_service
from app.services.media_service import save_ticket_image
from app.services.ticket_ws import ticket_ws_manager
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def _ticket_defaults() -> dict[str, Any]:
    return {
        "status": "Open",
        "category": "General Inquiry",
        "priority": "Medium",
        "assigneeId": None,
        "aiMeta": {},
    }


async def _require_ticket(ticket_id: str, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


async def _validate_book_access(
    book_id: str | None,
    author_id: str,
    db: AsyncIOMotorDatabase,
) -> str | None:
    if not book_id:
        return None

    # Support both ObjectId and string-style ids without changing existing data shape.
    candidates: list[Any] = [book_id]
    try:
        candidates.insert(0, ObjectId(book_id))
    except InvalidId:
        pass

    for candidate in candidates:
        book = await db.books.find_one({"_id": candidate, "authorId": author_id})
        if book:
            return str(candidate)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")


async def _find_book(book_id: str | None, db: AsyncIOMotorDatabase) -> dict[str, Any] | None:
    if not book_id:
        return None

    candidates: list[Any] = [book_id]
    try:
        candidates.insert(0, ObjectId(book_id))
    except InvalidId:
        pass

    for candidate in candidates:
        book = await db.books.find_one({"_id": candidate})
        if book:
            return book
    return None


def _build_message(
    ticket_id: str,
    prefix: str,
    message: str,
    admin_id: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "_id": f"{prefix}_{ticket_id}_{int(now.timestamp() * 1000)}",
        "ticketId": ticket_id,
        "senderRole": "admin",
        "senderId": admin_id,
        "message": message,
        "isInternal": prefix == "note",
        "createdAt": now,
    }


async def create_ticket(
    payload: TicketCreateRequest,
    author: dict[str, Any],
    db: AsyncIOMotorDatabase,
    *,
    image: UploadFile | None = None,
) -> dict[str, Any]:
    now = utc_now()
    ticket_id = f"tkt_{int(now.timestamp() * 1000)}"
    book_id = await _validate_book_access(payload.bookId, author["_id"], db)
    image_url = await save_ticket_image(ticket_id, image) if image else None

    ticket = {
        "_id": ticket_id,
        "authorId": author["_id"],
        "bookId": book_id,
        "imageUrl": image_url,
        "subject": payload.subject,
        "description": payload.description,
        **_ticket_defaults(),
        "createdAt": now,
        "updatedAt": now,
    }
    await db.tickets.insert_one(ticket)

    # Run AI category/priority calls in parallel to reduce ticket create latency.
    classification, priority = await asyncio.gather(
        ai_service.classify_ticket(payload.subject, payload.description),
        ai_service.prioritize_ticket(payload.subject, payload.description),
    )

    update_fields: dict[str, Any] = {
        "category": classification["category"],
        "priority": priority["priority"],
        "updatedAt": utc_now(),
        "aiMeta": {
            "classification": classification,
            "priority": priority,
            "draft": None,
        },
    }
    await db.tickets.update_one({"_id": ticket["_id"]}, {"$set": update_fields})
    ticket.update(update_fields)

    try:
        vector_id = ticket_vectors.add_ticket(
            title=payload.subject,
            description=payload.description,
            metadata={
                "ticket_id": ticket["_id"],
                "author_id": str(author["_id"]),
                "book_id": book_id,
                "category": classification["category"],
                "priority": priority["priority"],
                "status": ticket["status"],
                "created_at": now.isoformat(),
                "final_response": None,
            },
        )

        await db.tickets.update_one(
            {"_id": ticket["_id"]},
            {"$set": {"vectorId": vector_id, "updatedAt": utc_now()}},
        )
        ticket["vectorId"] = vector_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to store vector for ticket %s: %s", ticket["_id"], exc)

    await ticket_ws_manager.notify_ticket_update(db, ticket["_id"], event_type="ticket.updated")
    return ticket


async def list_author_tickets(author_id: str, db: AsyncIOMotorDatabase) -> tuple[list[dict[str, Any]], int]:
    query = {"authorId": author_id}
    items = [item async for item in db.tickets.find(query).sort("updatedAt", -1)]
    total = await db.tickets.count_documents(query)
    return items, total


async def get_ticket_for_author(ticket_id: str, author_id: str, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id, "authorId": author_id})
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    messages = [
        msg
        async for msg in db.ticket_messages.find({"ticketId": ticket_id, "isInternal": False}).sort("createdAt", 1)
    ]
    ticket["messages"] = messages
    return ticket


async def list_admin_tickets(filters: dict[str, Any], db: AsyncIOMotorDatabase) -> tuple[list[dict[str, Any]], int]:
    query = {key: filters[key] for key in ["status", "category", "priority", "assigneeId"] if filters.get(key)}
    items = [item async for item in db.tickets.find(query).sort([("priority", 1), ("createdAt", 1)])]
    total = await db.tickets.count_documents(query)
    return items, total


async def update_ticket(
    ticket_id: str,
    payload: AdminTicketUpdateRequest,
    admin: dict[str, Any],
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    ticket = await _require_ticket(ticket_id, db)
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not updates:
        return ticket

    updates["updatedAt"] = utc_now()
    await db.tickets.update_one({"_id": ticket_id}, {"$set": updates})

    await db.ticket_events.insert_one(
        {
            "_id": f"ev_{ticket_id}_{int(utc_now().timestamp() * 1000)}",
            "ticketId": ticket_id,
            "eventType": "ticket.updated",
            "by": admin["_id"],
            "payload": updates,
            "createdAt": utc_now(),
        }
    )

    ticket.update(updates)
    await ticket_ws_manager.notify_ticket_update(db, ticket_id, event_type="ticket.updated")
    return ticket


async def add_admin_reply(
    ticket_id: str,
    message: str,
    admin: dict[str, Any],
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    await _require_ticket(ticket_id, db)
    payload = _build_message(ticket_id, "msg", message, admin["_id"])
    await db.ticket_messages.insert_one(payload)
    await db.tickets.update_one(
        {"_id": ticket_id},
        {"$set": {"updatedAt": payload["createdAt"], "status": "In Progress"}},
    )
    await ticket_ws_manager.notify_ticket_update(db, ticket_id, event_type="ticket.reply")
    return payload


async def add_internal_note(
    ticket_id: str,
    note: str,
    admin: dict[str, Any],
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    await _require_ticket(ticket_id, db)
    payload = _build_message(ticket_id, "note", note, admin["_id"])
    await db.ticket_messages.insert_one(payload)
    await db.tickets.update_one({"_id": ticket_id}, {"$set": {"updatedAt": payload["createdAt"]}})
    return payload


async def assign_ticket(
    ticket_id: str,
    admin_id: str,
    assigned_by: dict[str, Any],
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    await _require_ticket(ticket_id, db)
    admin = await db.users.find_one({"_id": admin_id, "role": "admin"})
    if not admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")

    await db.tickets.update_one({"_id": ticket_id}, {"$set": {"assigneeId": admin_id}})
    await db.ticket_events.insert_one(
        {
            "ticketId": ticket_id,
            "type": "ticket_assigned",
            "assignedTo": admin_id,
            "assignedBy": assigned_by["_id"],
            "createdAt": utc_now(),
        }
    )
    return await db.tickets.find_one({"_id": ticket_id})


async def create_ticket_draft(ticket_id: str, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await _require_ticket(ticket_id, db)
    author = await db.users.find_one({"_id": ticket["authorId"]})
    if not author:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")

    book = await _find_book(ticket.get("bookId"), db)

    related_tickets = ticket_vectors.search_tickets(
        title=ticket.get("subject", ""),
        description=ticket.get("description", ""),
        limit=5,
        score_threshold=0.72,
        filters={"book_id": ticket.get("bookId")},
    )

    history: list[dict[str, Any]] = []
    for related in related_tickets:
        payload = related.get("payload", {})
        history.append(
            {
                "score": related.get("score"),
                "title": payload.get("title"),
                "description": payload.get("description"),
                "resolution": payload.get("final_response"),
                "topic": payload.get("topic"),
            }
        )

    draft = await ai_service.draft_response(
        ticket=ticket,
        author=author,
        book=book,
        historical_context=history,
    )

    await db.tickets.update_one(
        {"_id": ticket_id},
        {"$set": {"updatedAt": utc_now(), "aiMeta.draft": draft, "aiMeta.relatedTickets": history}},
    )

    return {"success": True, "draft": draft, "relatedTickets": history}


async def generate_draft_for_ticket(ticket_id: str, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """Backward-compatible alias while routes and callers move to the shorter name."""
    return await create_ticket_draft(ticket_id, db)
