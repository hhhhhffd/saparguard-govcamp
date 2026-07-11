from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import chats, collector, media, messages, stats
from app.config import settings
from app.database.session import close_database, engine
from app.logging import configure_logging
from app.web.routes import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings)
    logger.info("Starting API application")
    try:
        async with engine.connect():
            logger.info("Connected to PostgreSQL")
    except Exception:
        logger.exception("PostgreSQL connection check failed")
    yield
    await close_database()
    logger.info("API application stopped")


app = FastAPI(title="SaparGuard Telegram Collector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(web_router)
app.include_router(chats.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(collector.router, prefix="/api")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
