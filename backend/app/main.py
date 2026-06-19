"""FastAPI application entrypoint.

Wires together configuration, logging, the database, the API router and the
lifecycle of the background batch writer.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.database import init_db
from app.services.dependencies import batch_writer
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown: ensure schema, start/stop the batch writer."""
    logger.info("Starting %s", settings.app_name)
    init_db()
    batch_writer.start()
    try:
        yield
    finally:
        # Graceful shutdown: final flush so buffered counts are not lost.
        logger.info("Shutting down; flushing batch writer")
        batch_writer.stop()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

# Permissive CORS for the local frontend dev server / container.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", tags=["ops"])
def root() -> dict:
    return {"service": settings.app_name, "docs": "/docs"}
