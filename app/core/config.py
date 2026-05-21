from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "BookLeaf Author Support API"
    port: int = 8000

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "bookleaf_support"

    admin_email: str = "admin@bookleaf.test"

    jwt_secret: str = Field(default="change-me-access-secret", min_length=16)
    jwt_refresh_secret: str = Field(default="change-me-refresh-secret", min_length=16)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    groq_api_key: str = ""
    groq_model_classifier: str = "llama-3.1-8b-instant"
    groq_model_generator: str = "llama-3.3-70b-versatile"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "bookleaf_kb"

    ai_retry_attempts: int = 3
    ai_timeout_seconds: int = 20

    cors_origins: list[str] = ["http://localhost:3000"]

    upload_dir: str = "uploads"
    max_upload_mb: int = 5

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
