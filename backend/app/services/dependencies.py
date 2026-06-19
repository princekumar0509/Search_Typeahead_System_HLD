"""Application-wide singletons and FastAPI dependency providers.

These objects (the distributed cache and the batch writer) live for the
lifetime of the process and are shared across requests. They are created lazily
and wired into the app lifespan in ``main.py``.
"""
from __future__ import annotations

from app.batch.batch_writer import BatchWriter
from app.cache.distributed_cache import DistributedCache
from app.config import get_settings
from app.database import SessionLocal

_settings = get_settings()

# --- Distributed cache singleton -------------------------------------------
distributed_cache = DistributedCache(
    node_names=_settings.cache_nodes,
    virtual_nodes=_settings.cache_virtual_nodes,
    default_ttl=_settings.cache_ttl_seconds,
)

# --- Batch writer singleton -------------------------------------------------
batch_writer = BatchWriter(
    session_factory=SessionLocal,
    flush_interval=_settings.batch_flush_interval_seconds,
    flush_threshold=_settings.batch_flush_threshold,
)


def get_cache() -> DistributedCache:
    """FastAPI dependency returning the shared distributed cache."""
    return distributed_cache


def get_batch_writer() -> BatchWriter:
    """FastAPI dependency returning the shared batch writer."""
    return batch_writer
