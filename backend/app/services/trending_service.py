"""Trending-search business logic.

Two ranking modes (selected via the ``mode`` query param):

    * ``popularity`` (Mode 1): ``score = count``
        - Stable, reflects all-time winners. Good for evergreen head queries.
        - Trade-off: slow to react; a query spiking today cannot overtake a
          long-established one, so it misses "what's hot right now".

    * ``recency`` (Mode 2): ``score = count + recent_count * 10``
        - Boosts queries with activity in the recent window (the x10 weight
          lets a smaller but fresh signal compete with large all-time counts).
        - Trade-off: needs ``recent_count`` to be periodically decayed/reset by
          a maintenance job, otherwise it converges back to popularity. The
          weight (10) is a tunable knob trading stability vs. responsiveness.
"""
from __future__ import annotations

import logging

from app.models.schemas import TrendingItem
from app.repositories.query_repository import QueryRepository

logger = logging.getLogger(__name__)

POPULARITY = "popularity"
RECENCY = "recency"
_RECENT_WEIGHT = 10


class TrendingService:
    """Computes trending queries in the requested ranking mode."""

    def __init__(self, repo: QueryRepository, limit: int) -> None:
        self._repo = repo
        self._limit = limit

    def get_trending(self, mode: str) -> tuple[str, list[TrendingItem]]:
        """Return ``(mode, items)`` ranked by the chosen scoring function."""
        mode = (mode or POPULARITY).lower()
        recency_aware = mode == RECENCY

        rows = self._repo.get_trending(self._limit, recency_aware=recency_aware)

        items: list[TrendingItem] = []
        for r in rows:
            if recency_aware:
                score = float(r.count + r.recent_count * _RECENT_WEIGHT)
            else:
                score = float(r.count)
            items.append(
                TrendingItem(
                    query=r.query,
                    count=r.count,
                    recent_count=r.recent_count,
                    score=score,
                )
            )

        return (RECENCY if recency_aware else POPULARITY), items
