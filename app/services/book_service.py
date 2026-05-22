from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.utils.time import utc_now

async def list_author_books(author_id: str, db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    return [item async for item in db.books.find({"authorId": author_id}).sort("publicationDate", -1)]


async def publish_book(
    payload: Any,
    author: dict[str, Any],
    db: AsyncIOMotorDatabase,
) -> dict[str, Any]:
    now = utc_now()

    book = {
        "_id": f"book_{int(now.timestamp() * 1000)}",
        "authorId": str(author["_id"]),
        "title": payload.title.strip(),
        "isbn": payload.isbn,
        "genre": payload.genre.strip(),
        "publicationDate": payload.publicationDate,
        "status": "Submitted",
        "mrp": float(payload.mrp),
        "totalCopiesSold": 0,
        "totalRoyaltyEarned": 0.0,
        "royaltyPaid": 0.0,
        "royaltyPending": 0.0,
    }
    await db.books.insert_one(book)
    return book
