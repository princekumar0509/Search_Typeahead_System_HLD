"""Search-submission business logic.

``POST /search`` must:
    * return the dummy ``{"message": "Searched"}`` response,
    * increment the query's count (insert if it does not exist),
    * NOT write to the DB synchronously — increments are buffered by the
      batch writer and flushed in the background.

It also invalidates the cached suggestions for affected prefixes so popularity
changes become visible after the next miss (bounded staleness).
"""
from __future__ import annotations

import logging

from app.batch.batch_writer import BatchWriter
from app.cache.distributed_cache import DistributedCache

logger = logging.getLogger(__name__)


class SearchService:
    """Handles search submissions via the write-behind batch writer."""

    def __init__(self, batch_writer: BatchWriter, cache: DistributedCache) -> None:
        self._batch_writer = batch_writer
        self._cache = cache

    @staticmethod
    def normalize(query: str) -> str:
        return query.strip().lower()

    def submit(self, query: str) -> None:
        """Buffer an increment for ``query`` and invalidate stale prefix caches."""
        normalized = self.normalize(query)
        if not normalized:
            return

        # Write-behind: never hits the DB on the request path.
        self._batch_writer.increment(normalized, amount=1)
        logger.debug("Buffered search increment for %r", normalized)

        # Best-effort cache invalidation. We invalidate the prefixes that would
        # surface this query in a typeahead so a subsequent miss reloads fresh
        # popularity. Bounded to a few prefix lengths to limit fan-out.
        self._invalidate_affected_prefixes(normalized)

    def _invalidate_affected_prefixes(self, query: str, max_prefix_len: int = 6) -> None:
        upper = min(len(query), max_prefix_len)
        for length in range(1, upper + 1):
            prefix = query[:length]
            self._cache.invalidate(f"suggest:{prefix}")
