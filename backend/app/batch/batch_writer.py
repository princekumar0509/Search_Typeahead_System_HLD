"""Batched write-behind for search-count updates.

PROBLEM
-------
A naive design writes to the database on every ``POST /search``. Under load
that is one row update (plus a commit / WAL flush) per request — the database
becomes the bottleneck and most of those writes are just ``count += 1`` on the
same hot keys.

SOLUTION
--------
Buffer increments in memory (``search_buffer = {query: delta}``) and flush them
to Postgres in a single batched transaction either:

    * every ``flush_interval`` seconds (time trigger), or
    * as soon as the buffer holds ``flush_threshold`` distinct queries
      (size trigger).

So 80 searches for "iphone" + "java" collapse into 2 upserts.

FAILURE HANDLING & RECOVERY
---------------------------
* The buffer is swapped out under a lock before flushing, so new increments
  keep accumulating during a flush (no requests block on the DB).
* If a flush raises, the un-committed counts are **merged back** into the live
  buffer and retried on the next tick — no increments are silently lost.
* On shutdown ``stop()`` performs a final synchronous flush so in-flight counts
  are persisted.

TRADE-OFFS
----------
* Durability window: counts buffered in memory are lost if the process is
  hard-killed (SIGKILL / power loss). Acceptable here because search counts are
  approximate popularity signals, not money. A stricter system would use a
  write-ahead log / durable queue (e.g. Kafka) in front of the DB.
* Read-your-write: the ``count`` for a just-submitted query may lag by up to
  one flush interval. The typeahead tolerates slightly stale popularity.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.repositories.query_repository import QueryRepository

logger = logging.getLogger(__name__)


class BatchWriter:
    """Thread-based write-behind buffer for query count increments."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        flush_interval: float = 30.0,
        flush_threshold: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._flush_interval = flush_interval
        self._flush_threshold = flush_threshold

        # The live buffer: {query_text: pending_increment}.
        self._buffer: dict[str, int] = {}
        self._lock = threading.Lock()

        # Wakes the worker for an early (threshold-triggered) flush.
        self._flush_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Lightweight observability.
        self._total_flushes = 0
        self._total_buffered = 0

    # --- public API ---------------------------------------------------------
    def increment(self, query_text: str, amount: int = 1) -> None:
        """Record ``amount`` searches for ``query_text`` in the buffer."""
        if not query_text:
            return
        with self._lock:
            self._buffer[query_text] = self._buffer.get(query_text, 0) + amount
            self._total_buffered += amount
            should_flush = len(self._buffer) >= self._flush_threshold
        if should_flush:
            # Size trigger: ask the worker to flush right away.
            self._flush_event.set()

    def start(self) -> None:
        """Start the background flush worker."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="batch-writer", daemon=True)
        self._thread.start()
        logger.info(
            "BatchWriter started (interval=%ss threshold=%d queries)",
            self._flush_interval,
            self._flush_threshold,
        )

    def stop(self) -> None:
        """Stop the worker and perform a final flush so nothing is lost."""
        self._stop_event.set()
        self._flush_event.set()
        if self._thread:
            self._thread.join(timeout=self._flush_interval + 5)
        self._flush()  # final synchronous flush
        logger.info("BatchWriter stopped after %d flushes", self._total_flushes)

    def stats(self) -> dict[str, int]:
        with self._lock:
            pending = len(self._buffer)
        return {
            "pending_queries": pending,
            "total_flushes": self._total_flushes,
            "total_buffered_increments": self._total_buffered,
        }

    # --- worker internals ---------------------------------------------------
    def _run(self) -> None:
        """Worker loop: flush on interval or when signalled by the size trigger."""
        while not self._stop_event.is_set():
            # Wait up to flush_interval, but wake early on a threshold trigger.
            triggered = self._flush_event.wait(timeout=self._flush_interval)
            self._flush_event.clear()
            if self._stop_event.is_set():
                break
            reason = "threshold" if triggered else "interval"
            self._flush(reason=reason)

    def _flush(self, reason: str = "shutdown") -> None:
        """Atomically swap out the buffer and persist it in one transaction."""
        # Swap the buffer out under the lock; new increments accumulate freshly.
        with self._lock:
            if not self._buffer:
                return
            pending, self._buffer = self._buffer, {}

        session = self._session_factory()
        try:
            repo = QueryRepository(session)
            affected = repo.batch_upsert_increment(pending)
            self._total_flushes += 1
            logger.info(
                "Flushed batch (%s): %d distinct queries, %d total increments",
                reason,
                affected,
                sum(pending.values()),
            )
        except Exception:  # noqa: BLE001 - we deliberately recover any failure
            session.rollback()
            # Recovery: merge the failed counts back into the live buffer so
            # they are retried on the next flush. Existing increments win-merge.
            with self._lock:
                for query_text, delta in pending.items():
                    self._buffer[query_text] = self._buffer.get(query_text, 0) + delta
            logger.exception("Batch flush failed (%s); %d queries requeued", reason, len(pending))
        finally:
            session.close()
