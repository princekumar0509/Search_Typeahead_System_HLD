"""Suggestion (typeahead) business logic.

Implements the cache-aside flow for ``GET /suggest``:

    1. Build the cache key from the normalised prefix.
    2. Resolve the responsible cache node via consistent hashing.
    3. On cache hit  -> return cached suggestions.
    4. On cache miss -> query the DB, store in cache (with TTL), return.
"""
from __future__ import annotations

import logging

from app.cache.distributed_cache import DistributedCache
from app.models.schemas import Suggestion
from app.repositories.query_repository import QueryRepository
from app.utils.metrics import metrics

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "suggest:"


class SuggestionService:
    """Coordinates the cache and repository to serve suggestions."""

    def __init__(self, repo: QueryRepository, cache: DistributedCache, limit: int) -> None:
        self._repo = repo
        self._cache = cache
        self._limit = limit

    @staticmethod
    def normalize(prefix: str) -> str:
        """Normalise a prefix for consistent caching (trim + lowercase)."""
        return prefix.strip().lower()

    def cache_key(self, prefix: str) -> str:
        return f"{_CACHE_KEY_PREFIX}{self.normalize(prefix)}"

    def get_suggestions(self, prefix: str) -> tuple[list[Suggestion], bool, str]:
        """Return ``(suggestions, cache_hit, node_name)`` for ``prefix``.

        The cache key is routed through the consistent hash ring, so the same
        prefix always hits the same node.
        """
        normalized = self.normalize(prefix)
        key = self.cache_key(normalized)
        node = self._cache.get_node_name(key)

        if not normalized:
            return [], False, node

        hit, cached = self._cache.get(key)
        if hit:
            metrics.record_cache_hit()
            logger.debug("Cache HIT for %r on %s", normalized, node)
            return [Suggestion(**item) for item in cached], True, node

        # --- cache miss: fall back to the database --------------------------
        metrics.record_cache_miss()
        logger.debug("Cache MISS for %r on %s -> querying DB", normalized, node)
        rows = self._repo.get_suggestions(normalized, self._limit)
        suggestions = [Suggestion(query=r.query, count=r.count) for r in rows]

        # Store the serialised form so cached values are plain dicts.
        self._cache.set(key, [s.model_dump() for s in suggestions])
        return suggestions, False, node

    def invalidate(self, prefix: str) -> bool:
        """Invalidate the cached suggestions for a prefix."""
        return self._cache.invalidate(self.cache_key(prefix))
