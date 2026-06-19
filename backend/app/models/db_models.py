"""SQLAlchemy ORM models.

Mirrors the SQL schema in ``db/schema.sql``:

    queries(
        id            SERIAL PRIMARY KEY,
        query         TEXT UNIQUE,
        count         BIGINT,
        recent_count  BIGINT,
        last_searched TIMESTAMP
    )
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Query(Base):
    """A single search query and its popularity counters."""

    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # The normalised query text. Unique so an upsert can target it.
    query: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # All-time popularity counter.
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Popularity accrued in the recent window; used by the recency-aware
    # trending mode and periodically decayed/reset by a maintenance job.
    recent_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    last_searched: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )

    # A prefix range scan (query LIKE 'iph%') uses this btree index.
    __table_args__ = (
        Index("ix_queries_query", "query"),
        Index("ix_queries_count", "count"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Query {self.query!r} count={self.count} recent={self.recent_count}>"
