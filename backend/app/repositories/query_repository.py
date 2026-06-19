"""Repository layer for the ``queries`` table.

The repository is the *only* place that knows about SQL/ORM details. Services
depend on these methods, not on SQLAlchemy directly, which keeps the business
logic database-agnostic and easy to test.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.db_models import Query
from app.utils.metrics import metrics

logger = logging.getLogger(__name__)


class QueryRepository:
    """Data-access methods for search queries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # --- reads --------------------------------------------------------------
    def get_suggestions(self, prefix: str, limit: int) -> list[Query]:
        """Return up to ``limit`` queries matching ``prefix``, by popularity.

        A case-insensitive prefix match (``query ILIKE 'iph%'``) backed by the
        btree index on ``query`` powers the typeahead. Results are ordered by
        all-time ``count`` descending.
        """
        if not prefix:
            return []

        # Escape LIKE wildcards in user input so a literal '%' or '_' does not
        # broaden the match.
        safe = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"{safe}%"

        stmt = (
            select(Query)
            .where(Query.query.ilike(pattern, escape="\\"))
            .order_by(Query.count.desc())
            .limit(limit)
        )
        rows = list(self._db.scalars(stmt))
        metrics.record_db_read()
        return rows

    def get_trending(self, limit: int, recency_aware: bool) -> list[Query]:
        """Return the top ``limit`` queries by trending score.

        * popularity-only mode: ``score = count``
        * recency-aware mode:   ``score = count + recent_count * 10``

        The score is computed in SQL so ordering/limiting happen in the
        database rather than pulling the whole table into Python.
        """
        if recency_aware:
            score = (Query.count + Query.recent_count * 10).label("score")
        else:
            score = Query.count.label("score")

        stmt = select(Query, score).order_by(score.desc()).limit(limit)
        rows = list(self._db.execute(stmt))
        metrics.record_db_read()
        # Each row is (Query, score); return the ORM objects, score recomputed
        # in the service for the response payload.
        return [row[0] for row in rows]

    def get_by_query(self, query_text: str) -> Query | None:
        stmt = select(Query).where(Query.query == query_text)
        result = self._db.scalars(stmt).first()
        metrics.record_db_read()
        return result

    # --- writes -------------------------------------------------------------
    def upsert_increment(self, query_text: str, increment: int) -> None:
        """Insert a new query or increment an existing one by ``increment``.

        Uses Postgres ``INSERT ... ON CONFLICT DO UPDATE`` so the
        insert-or-increment is a single atomic statement (no read-modify-write
        race between concurrent workers).
        """
        stmt = pg_insert(Query).values(
            query=query_text,
            count=increment,
            recent_count=increment,
            last_searched=func.now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Query.query],
            set_={
                "count": Query.count + increment,
                "recent_count": Query.recent_count + increment,
                "last_searched": func.now(),
            },
        )
        self._db.execute(stmt)
        metrics.record_db_write()

    def batch_upsert_increment(self, counts: dict[str, int]) -> int:
        """Apply a batch of ``{query: increment}`` upserts in one transaction.

        Returns the number of rows affected. This is the database-facing half
        of the batch-writer: instead of N statements we issue N upserts inside
        a single transaction/commit, dramatically reducing commit overhead and
        WAL flushes.
        """
        if not counts:
            return 0

        for query_text, increment in counts.items():
            if increment <= 0:
                continue
            self.upsert_increment(query_text, increment)

        self._db.commit()
        # Count as a single logical batch write for metrics clarity.
        logger.info("Batch upsert committed for %d distinct queries", len(counts))
        return len(counts)

    def reset_recent_counts(self) -> None:
        """Reset the recency window (would be called by a periodic decay job)."""
        self._db.execute(text("UPDATE queries SET recent_count = 0"))
        self._db.commit()
        metrics.record_db_write()
