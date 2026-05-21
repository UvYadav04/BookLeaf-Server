from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_db
from app.core.security import decode_access_token, require_role
from app.schemas.book import BookCreateRequest
from app.schemas.ticket import TicketCreateRequest
from app.services.book_service import list_author_books, publish_book
from app.services.ticket_service import create_ticket, get_ticket_for_author, list_author_tickets
from app.services.ticket_ws import ticket_ws_manager
from app.utils.serialize import serialize_document, serialize_documents

router = APIRouter()


async def _authenticate_author_ws(access_token: str, db: AsyncIOMotorDatabase) -> dict:
    payload = decode_access_token(access_token)
    if payload.get("role") != "author":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = await db.users.find_one({"_id": user_id, "role": "author"})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/books")
async def my_books(
    current_user: dict = Depends(require_role("author")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    books = await list_author_books(current_user["_id"], db)
    return {"items": serialize_documents(books)}


@router.post("/books")
async def create_book(
    payload: BookCreateRequest,
    current_user: dict = Depends(require_role("author")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    book = await publish_book(payload, current_user, db)
    return {"item": serialize_document(book)}


@router.post("/tickets")
async def create_author_ticket(
    subject: str = Form(..., min_length=3, max_length=180),
    description: str = Form(..., min_length=10, max_length=5000),
    bookId: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    current_user: dict = Depends(require_role("author")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    normalized_book_id = bookId.strip() if bookId and bookId.strip() else None
    if normalized_book_id in {"General", "Account Level"}:
        normalized_book_id = None

    payload = TicketCreateRequest(
        bookId=normalized_book_id,
        subject=subject,
        description=description,
    )
    ticket = await create_ticket(payload, current_user, db, image=image)
    return {"item": serialize_document(ticket)}


@router.get("/tickets")
async def my_tickets(
    current_user: dict = Depends(require_role("author")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    items, total = await list_author_tickets(current_user["_id"], db)
    return {"items": serialize_documents(items), "total": total}


@router.websocket("/tickets/ws")
async def tickets_websocket(
    websocket: WebSocket,
    accessToken: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        current_user = await _authenticate_author_ws(accessToken, db)
    except HTTPException:
        await websocket.close(code=4401)
        return

    author_id = current_user["_id"]
    await ticket_ws_manager.connect(author_id, websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ticket_ws_manager.disconnect(author_id, websocket)
    except Exception:
        ticket_ws_manager.disconnect(author_id, websocket)


@router.get("/tickets/{ticket_id}")
async def my_ticket_detail(
    ticket_id: str,
    current_user: dict = Depends(require_role("author")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    ticket = await get_ticket_for_author(ticket_id, current_user["_id"], db)
    return {"item": serialize_document(ticket)}
