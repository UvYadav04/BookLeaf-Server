from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, SignupRequest, UserInfo
from app.services.auth_service import get_user_info, login_user, refresh_session, signup_user

router = APIRouter()


@router.post("/signup", response_model=LoginResponse)
async def signup(payload: SignupRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await signup_user(payload, db)

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await login_user(payload, db)

@router.get("/me", response_model=UserInfo)
async def me(current_user: dict = Depends(get_current_user)):
    return get_user_info(current_user)




@router.post("/refresh")
async def refresh(payload: RefreshRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    tokens = await refresh_session(payload.refreshToken, db)
    return {"tokens": tokens}
