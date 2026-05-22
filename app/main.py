from contextlib import asynccontextmanager
import logging
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.routes import admin, author, auth, health

logger = logging.getLogger(__name__)


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
    start = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - start) * 1000

    # Keep access logs concise but useful for tracing slow/error requests.
    log_message = "%s %s -> %s (%.1fms)"
    args = (request.method, request.url.path, response.status_code, elapsed_ms)
    if response.status_code >= 500:
        logger.error(log_message, *args)
    else:
        logger.info(log_message, *args)
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
