from __future__ import annotations

from typing import Any
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger("app.core.database")

client: AsyncIOMotorClient[Any] | None = None
db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    global client, db
    logger.info("Connecting to MongoDB at %s", settings.mongo_uri)
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]
    logger.info("Connected to MongoDB database: %s", settings.mongo_db_name)


async def close_mongo_connection() -> None:
    global client
    if client:
        logger.info("Closing MongoDB connection")
        client.close()
        logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if db is None:
        logger.error("Attempted to access the database before initialization")
        raise RuntimeError("Database not initialized")
    return db
