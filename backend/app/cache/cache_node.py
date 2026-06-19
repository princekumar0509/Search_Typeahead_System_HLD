"""A single in-memory cache node with per-entry TTL.

This simulates one cache server (e.g. a Redis instance). In a real deployment
each ``CacheNode`` would be a network client to a distinct server; here they
are in-process dictionaries so the whole distributed-cache behaviour can be
demonstrated without external infrastructure.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _Entry:
    """A cached value with its absolute expiry timestamp (epoch seconds)."""

    value: Any
    expires_at: float


class CacheNode:
    """Thread-safe key/value store with TTL and lazy expiry."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._store: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, Any]:
        """Return ``(hit, value)``. A miss (absent or expired) returns ``(False, None)``."""
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            if entry.expires_at <= now:
                # Lazy expiry: drop the stale entry on read.
                del self._store[key]
                return False, None
            return True, entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store ``value`` under ``key`` for ``ttl_seconds``."""
        with self._lock:
            self._store[key] = _Entry(value=value, expires_at=time.time() + ttl_seconds)

    def invalidate(self, key: str) -> bool:
        """Remove a single key. Returns True if a value was present."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def ttl_remaining(self, key: str) -> int:
        """Seconds until ``key`` expires, or 0 if absent/expired."""
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.expires_at <= now:
                return 0
            return int(round(entry.expires_at - now))

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)
