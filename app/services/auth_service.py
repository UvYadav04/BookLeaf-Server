from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.schemas.auth import LoginRequest, SignupRequest


def _normalize_email(email: str) -> str:
    return email.lower().strip()


def is_admin_user(user: dict[str, Any]) -> bool:
    email = _normalize_email(user.get("email", ""))
    admin_email = _normalize_email(settings.admin_email)
    return user.get("role") == "admin" or (bool(admin_email) and email == admin_email)


def get_user_info(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["_id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "isAdmin": is_admin_user(user),
    }


async def signup_user(payload: SignupRequest, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    now = datetime.now(timezone.utc)
    admin_emails = [
        e.strip().lower()
        for e in settings.admin_email.split(",")
    ]

    role = "admin" if email.lower() in admin_emails else "author"  
    user: dict[str, Any] = {
        "_id": f"usr_{uuid.uuid4().hex[:12]}",
        "name": payload.name.strip(),
        "email": email,
        "passwordHash": hash_password(payload.password),
        "role": role,
        "createdAt": now,
        "updatedAt": now,
    }
    await db.users.insert_one(user)

    access_token = create_access_token(user["_id"], user["role"])
    refresh_token = create_refresh_token(user["_id"])

    return {
        "user": get_user_info(user),
        "tokens": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "tokenType": "bearer",
        },
    }


async def login_user(payload: LoginRequest, db: AsyncIOMotorDatabase) -> dict[str, Any]:
    user = await db.users.find_one({"email": _normalize_email(payload.email)})
    print(user)
    if not user or not verify_password(payload.password, user["passwordHash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(user["_id"], user["role"])
    refresh_token = create_refresh_token(user["_id"])

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

    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return {
        "accessToken": create_access_token(user["_id"], user["role"]),
        "refreshToken": create_refresh_token(user["_id"]),
        "tokenType": "bearer",
    }
