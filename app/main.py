
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.routes import admin, author, auth, health
import logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="BookLeaf Author Support API",
    version="0.1.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger = logging.getLogger("uvicorn.access")
    # Log incoming request method and path
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    response = await call_next(request)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

upload_path = Path(settings.upload_dir)
upload_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(upload_path)), name="media")

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(author.router, prefix="/author", tags=["author"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
