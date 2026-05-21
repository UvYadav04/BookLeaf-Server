from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_db
from app.core.security import require_role
from app.schemas.ticket import (
    AdminInternalNoteRequest,
    AdminReplyRequest,
    AdminTicketUpdateRequest,
)
from app.services.ticket_service import (
    add_admin_reply,
    add_internal_note,
    assign_ticket,
    generate_draft_for_ticket,
    list_admin_tickets,
    update_ticket,
)
from app.utils.serialize import serialize_document, serialize_documents

router = APIRouter()


@router.get("/tickets")
async def all_tickets(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assigneeId: str | None = Query(default=None),
    _: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    filters = {
        "status": status,
        "category": category,
        "priority": priority,
        "assigneeId": assigneeId,
    }

    items, total = await list_admin_tickets(filters, db)

    return {
        "items": serialize_documents(items),
        "total": total,
    }


@router.get("/tickets/messages")
async def get_ticket_messages(
    _: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    messages = await db.ticket_messages.find().sort("createdAt", 1).to_list(length=None)
    return {
        "items": serialize_documents(messages)
    }


@router.patch("/tickets/{ticket_id}")
async def patch_ticket(
    ticket_id: str,
    payload: AdminTicketUpdateRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    ticket = await update_ticket(
        ticket_id,
        payload,
        current_user,
        db,
    )

    return {
        "item": serialize_document(ticket)
    }


@router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: str,
    payload: AdminReplyRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    message = await add_admin_reply(
        ticket_id,
        payload.message,
        current_user,
        db,
    )

    return {
        "item": serialize_document(message)
    }


# Add internal admin-only note
@router.post("/tickets/{ticket_id}/notes")
async def internal_note(
    ticket_id: str,
    payload: AdminInternalNoteRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    note = await add_internal_note(
        ticket_id,
        payload.note,
        current_user,
        db,
    )

    return {
        "item": serialize_document(note)
    }


# Assign ticket to another admin
@router.post("/tickets/{ticket_id}/assign/{admin_id}")
async def assign_ticket_to_admin(
    ticket_id: str,
    admin_id: str,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin id is required",
        )

    ticket = await assign_ticket(
        ticket_id=ticket_id,
        admin_id=admin_id,
        assigned_by=current_user,
        db=db,
    )

    return {
        "item": serialize_document(ticket)
    }


@router.post("/tickets/{ticket_id}/draft")
async def draft_ticket_response(
    ticket_id: str,
    _: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    draft = await generate_draft_for_ticket(
        ticket_id,
        db,
    )

    return {
        "item": draft
    }

@router.get("/admins")
async def list_admins(
    _: dict = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    admins = await db.users.find(
        {"role": "admin"},
        {
            "_id": 1,
            "name": 1,
            "email": 1,
        },
    ).to_list(length=None)

    return {
        "items": serialize_documents(admins)
    }