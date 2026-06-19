"""HTTP routes for the Search Typeahead System.

Endpoints:
    GET  /suggest?q=<prefix>      -> up to N popularity-sorted suggestions
    POST /search                  -> dummy response + buffered count increment
    GET  /trending?mode=<mode>    -> top trending queries
    GET  /cache/debug?prefix=<p>  -> which node owns a prefix + hit/TTL info
    GET  /metrics                 -> latency / cache / DB instrumentation
    GET  /health                  -> liveness probe
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_search_service,
    get_suggestion_service,
    get_trending_service,
)
from app.config import get_settings
from app.models.schemas import (
    CacheDebugResponse,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SuggestResponse,
    TrendingResponse,
)
from app.services.dependencies import get_cache
from app.services.search_service import SearchService
from app.services.suggestion_service import SuggestionService
from app.services.trending_service import TrendingService
from app.utils.metrics import metrics

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.get("/suggest", response_model=SuggestResponse, tags=["suggest"])
def suggest(
    q: str = Query("", description="The prefix typed by the user"),
    service: SuggestionService = Depends(get_suggestion_service),
) -> SuggestResponse:
    """Return up to N suggestions matching ``q``, sorted by popularity."""
    start = time.perf_counter()
    suggestions, cache_hit, node = service.get_suggestions(q)
    metrics.record_latency("/suggest", (time.perf_counter() - start) * 1000)
    return SuggestResponse(
        prefix=q,
        suggestions=suggestions,
        cache_hit=cache_hit,
        node=node,
    )


@router.post("/search", response_model=SearchResponse, tags=["search"])
def search(
    body: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Submit a search: buffer a count increment, return the dummy response."""
    start = time.perf_counter()
    service.submit(body.query)
    metrics.record_latency("/search", (time.perf_counter() - start) * 1000)
    return SearchResponse(message="Searched")


@router.get("/trending", response_model=TrendingResponse, tags=["trending"])
def trending(
    mode: str = Query("popularity", description="Ranking mode: 'popularity' or 'recency'"),
    service: TrendingService = Depends(get_trending_service),
) -> TrendingResponse:
    """Return the top trending queries in the requested ranking mode."""
    start = time.perf_counter()
    resolved_mode, items = service.get_trending(mode)
    metrics.record_latency("/trending", (time.perf_counter() - start) * 1000)
    return TrendingResponse(mode=resolved_mode, items=items)


@router.get("/cache/debug", response_model=CacheDebugResponse, tags=["cache"])
def cache_debug(
    prefix: str = Query(..., description="The prefix to inspect"),
) -> CacheDebugResponse:
    """Inspect cache routing/state for a prefix without mutating it."""
    cache = get_cache()
    key = f"suggest:{prefix.strip().lower()}"
    node = cache.get_node_name(key)
    cache_hit = cache.is_hit(key)
    ttl_remaining = cache.ttl_remaining(key)
    return CacheDebugResponse(
        prefix=prefix,
        node=node,
        cache_hit=cache_hit,
        ttl_remaining=ttl_remaining,
    )


@router.get("/metrics", tags=["ops"])
def get_metrics() -> dict:
    """Return latency percentiles, cache hit rate and DB read/write counts."""
    snapshot = metrics.snapshot()
    snapshot["cache_node_sizes"] = get_cache().stats()
    return snapshot


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(name=settings.app_name, version="1.0.0")
