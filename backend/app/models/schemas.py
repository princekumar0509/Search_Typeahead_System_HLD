"""Pydantic request/response schemas (the API contract).

Keeping these separate from the ORM models enforces a clean boundary: the
transport layer never leaks database internals, and validation happens at the
edge.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Suggestion(BaseModel):
    """A single typeahead suggestion."""

    query: str
    count: int


class SuggestResponse(BaseModel):
    """Response for ``GET /suggest``."""

    prefix: str
    suggestions: list[Suggestion]
    cache_hit: bool
    node: str


class SearchRequest(BaseModel):
    """Body for ``POST /search``."""

    query: str = Field(..., min_length=1, max_length=512, description="The submitted search query")


class SearchResponse(BaseModel):
    """Response for ``POST /search`` (dummy per the spec)."""

    message: str = "Searched"


class TrendingItem(BaseModel):
    """A trending query with its computed score."""

    query: str
    count: int
    recent_count: int
    score: float


class TrendingResponse(BaseModel):
    """Response for ``GET /trending``."""

    mode: str
    items: list[TrendingItem]


class CacheDebugResponse(BaseModel):
    """Response for ``GET /cache/debug``."""

    prefix: str
    node: str
    cache_hit: bool
    ttl_remaining: int


class HealthResponse(BaseModel):
    status: str = "ok"
    name: str
    version: str
