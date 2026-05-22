from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    refreshToken: str


class AuthTokens(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "bearer"


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserSummary(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    isAdmin: bool
    # phone: str
    # city: str

class UserInfo(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    isAdmin: bool


class LoginResponse(BaseModel):
    user: UserSummary
    tokens: AuthTokens
