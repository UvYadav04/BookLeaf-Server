from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas.ticket import AdminTicketUpdateRequest, TicketCreateRequest
from app.services.ai_service import ai_service
from app.services.media_service import save_ticket_image
from app.services.ticket_ws import ticket_ws_manager
from app.utils.time import utc_now


def _ticket_defaults() -> dict[str, Any]:
    return {
        "status": "Open",
        "category": "General Inquiry",
        "priority": "Medium",
        "assigneeId": None,
        "aiMeta": {},
    }

from bson import ObjectId
from bson.errors import InvalidId


async def create_ticket(
    payload: TicketCreateRequest,
    author: dict[str, Any],
    db: AsyncIOMotorDatabase,
    *,
    image: UploadFile | None = None,
) -> dict[str, Any]:
    now = utc_now()

    ticket_id = f"tkt_{int(now.timestamp() * 1000)}"

    book_id = payload.bookId
    book = None

    if book_id:
        try:
            parsed_book_id = ObjectId(book_id)

            book = await db.books.find_one(
                {
                    "_id": parsed_book_id,
                    "authorId": author["_id"],
                }
            )

            if not book:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Book not found",
                )

            book_id = str(parsed_book_id)

        except InvalidId:
            pass

    image_url = (
        await save_ticket_image(ticket_id, image)
        if image
        else None
    )

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

    classification = await ai_service.classify_ticket(
        payload.subject,
        payload.description,
    )

    priority = await ai_service.prioritize_ticket(
        payload.subject,
        payload.description,
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

    await db.tickets.update_one(
        {"_id": ticket["_id"]},
        {"$set": update_fields},
    )

    ticket.update(update_fields)


    try:
        vector_metadata = {
            "ticket_id": ticket["_id"],
            "author_id": str(author["_id"]),
            "book_id": book_id,
            "category": classification["category"],
            "priority": priority["priority"],
            "status": ticket["status"],
            "created_at": now.isoformat(),
            "final_response": None,
        }

        vector_id = ticket_vector_store.add_ticket(
            title=payload.subject,
            description=payload.description,
            metadata=vector_metadata,
        )

        await db.tickets.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "vectorId": vector_id,
                    "updatedAt": utc_now(),
                }
            },
        )

        ticket["vectorId"] = vector_id

    except Exception as e:
        print(
            f"Failed to store ticket in vector DB: {str(e)}"
        )

    await ticket_ws_manager.notify_ticket_update(
        db,
        ticket["_id"],
        event_type="ticket.updated",
    )

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
        item
        async for item in db.ticket_messages.find({"ticketId": ticket_id, "isInternal": False}).sort("createdAt", 1)
    ]
    ticket["messages"] = messages
    return ticket


async def list_admin_tickets(filters: dict[str, Any], db: AsyncIOMotorDatabase) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {}
    for key in ["status", "category", "priority", "assigneeId"]:
        if filters.get(key):
            query[key] = filters[key]

    items = [item async for item in db.tickets.find(query).sort([("priority", 1), ("createdAt", 1)])]
    total = await db.tickets.count_documents(query)
    return items, total


async def update_ticket(ticket_id: str, payload: AdminTicketUpdateRequest, admin: dict[str, Any], db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return ticket

    updates["updatedAt"] = utc_now()
    await db.tickets.update_one({"_id": ticket_id}, {"$set": updates})

    await db.ticket_events.insert_one(
        {
            "_id": f"ev_{ticket_id}_{int(datetime.utcnow().timestamp() * 1000)}",
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


async def add_admin_reply(ticket_id: str, message: str, admin: dict[str, Any], db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    now = utc_now()
    payload = {
        "_id": f"msg_{ticket_id}_{int(now.timestamp() * 1000)}",
        "ticketId": ticket_id,
        "senderRole": "admin",
        "senderId": admin["_id"],
        "message": message,
        "isInternal": False,
        "createdAt": now,
    }
    await db.ticket_messages.insert_one(payload)
    await db.tickets.update_one({"_id": ticket_id}, {"$set": {"updatedAt": now, "status": "In Progress"}})
    await ticket_ws_manager.notify_ticket_update(db, ticket_id, event_type="ticket.reply")
    return payload


async def add_internal_note(ticket_id: str, note: str, admin: dict[str, Any], db: AsyncIOMotorDatabase) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    now = utc_now()
    payload = {
        "_id": f"note_{ticket_id}_{int(now.timestamp() * 1000)}",
        "ticketId": ticket_id,
        "senderRole": "admin",
        "senderId": admin["_id"],
        "message": note,
        "isInternal": True,
        "createdAt": now,
    }
    await db.ticket_messages.insert_one(payload)
    await db.tickets.update_one({"_id": ticket_id}, {"$set": {"updatedAt": now}})
    return payload

async def assign_ticket(
    ticket_id: str,
    admin_id: str,
    assigned_by: dict,
    db: AsyncIOMotorDatabase,
):
    # Check ticket exists
    ticket = await db.tickets.find_one({"_id": ticket_id})

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    # Check admin exists
    admin = await db.users.find_one({
        "_id": admin_id,
        "role": "admin",
    })

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )


    # Update assignment
    await db.tickets.update_one(
        {"_id": ticket_id},
        {
            "$set": {
                "assigneeId": admin_id,
            }
        },
    )

    # Optional: create ticket event/activity log
    await db.ticket_events.insert_one({
        "ticketId": ticket_id,
        "type": "ticket_assigned",
        "assignedTo": admin_id,
        "assignedBy": assigned_by["_id"],
    })

    updated_ticket = await db.tickets.find_one({
        "_id": ticket_id
    })

    return updated_ticket


from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.qdrant import ticket_vector_store
from ..utils.time import utc_now


async def generate_draft_for_ticket(
    ticket_id: str,
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    ticket = await db.tickets.find_one({"_id": ticket_id})

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    author = await db.users.find_one(
        {"_id": ticket["authorId"]}
    )

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found",
        )

    book = None

    if ticket.get("bookId"):
        book = await db.books.find_one(
            {"_id": ticket["bookId"]}
        )

    related_tickets = ticket_vector_store.search_tickets(
        title=ticket.get("subject", ""),
        description=ticket.get("description", ""),
        limit=5,
        score_threshold=0.72,
        filters={
            # "status": "resolved",
            "book_id":ticket["bookId"]
        },
    )

    print(related_tickets)

    historical_context = []

    for related in related_tickets:
        payload = related.get("payload", {})

        historical_context.append(
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
        historical_context=historical_context,
    )

    await db.tickets.update_one(
        {"_id": ticket_id},
        {
            "$set": {
                "updatedAt": utc_now(),
                "aiMeta.draft": draft,
                "aiMeta.relatedTickets": historical_context,
            }
        },
    )

    return {
        "success": True,
        "draft": draft,
        "relatedTickets": historical_context,
    }