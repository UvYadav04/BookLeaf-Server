from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.schemas.auth import LoginRequest, SignupRequest

logger = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    return email.lower().strip()


def _admin_emails() -> set[str]:
    return {email.strip().lower() for email in settings.admin_email.split(",") if email.strip()}


def _user_id_filter(user_id: str) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [{"_id": user_id}]
    try:
        filters.append({"_id": ObjectId(user_id)})
    except (InvalidId, TypeError):
        pass
    return {"$or": filters} if len(filters) > 1 else filters[0]


async def _migrate_book_author_ids(db: AsyncIOMotorDatabase) -> None:
    """
    Normalize legacy books where authorId was stored using users.id instead of users._id.
    Runs on login to self-heal existing data without manual migration scripts.
    """
    total_modified = 0
    cursor = db.users.find({"id": {"$exists": True}}, {"_id": 1, "id": 1})
    async for user in cursor:
        legacy_user_id = str(user.get("id", "")).strip()
        current_user_id = str(user["_id"])
        if not legacy_user_id or legacy_user_id == current_user_id:
            continue

        result = await db.books.update_many(
            {"authorId": legacy_user_id},
            {"$set": {"authorId": current_user_id}},
        )
        total_modified += result.modified_count

    if total_modified:
        logger.info("Migrated %s book(s) from legacy authorId to _id", total_modified)


def is_admin_user(user: dict[str, Any]) -> bool:
    email = _normalize_email(user.get("email", ""))
    return user.get("role", "").lower() == "admin" or email in _admin_emails()


def get_user_info(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "email": user["email"],
        "role": user["role"].lower(),
        "isAdmin": is_admin_user(user),
    }


async def signup_user(payload: SignupRequest, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    now = datetime.now(timezone.utc)
    role = "admin" if email in _admin_emails() else "author"
    user: dict[str, Any] = {
        "name": payload.name.strip(),
        "email": email,
        "passwordHash": hash_password(payload.password),
        "role": role,
        "createdAt": now,
        "updatedAt": now,
    }
    await db.users.insert_one(user)

    access_token = create_access_token(str(user["_id"]), user["role"])
    refresh_token = create_refresh_token(str(user["_id"]))

    return {
        "user": get_user_info(user),
        "tokens": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "tokenType": "bearer",
        },
    }


async def login_user(payload: LoginRequest, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["passwordHash"]):
        logger.info("Login failed for email=%s", email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # await _migrate_book_author_ids(db)

    access_token = create_access_token(str(user["_id"]), user["role"])
    refresh_token = create_refresh_token(str(user["_id"]))

    return {
        "user": get_user_info(user),
        "tokens": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "tokenType": "bearer",
        },
    }


async def refresh_session(refresh_token: str, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    try:
        payload = jwt.decode(refresh_token, settings.jwt_refresh_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    exp = payload.get("exp")
    if not user_id or not exp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    if datetime.fromtimestamp(exp, timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = await db.users.find_one(_user_id_filter(str(user_id)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return {
        "accessToken": create_access_token(str(user["_id"]), user["role"]),
        "refreshToken": create_refresh_token(str(user["_id"])),
        "tokenType": "bearer",
    }
