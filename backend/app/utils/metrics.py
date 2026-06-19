"""In-process performance metrics.

This is a deliberately lightweight, dependency-free metrics collector good
enough for a single-process demo. In production you would export these to
Prometheus / StatsD instead of holding them in memory.

It tracks:
    * request latency percentiles (p50 / p95) per endpoint
    * cache hits / misses (-> hit rate)
    * database read / write counts
"""
from __future__ import annotations

import threading
from bisect import insort
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _LatencyWindow:
    """A bounded, sorted window of latency samples (milliseconds)."""

    max_samples: int = 5000
    samples: list[float] = field(default_factory=list)

    def add(self, value_ms: float) -> None:
        insort(self.samples, value_ms)
        if len(self.samples) > self.max_samples:
            # Drop the median-ish middle element to keep the window bounded
            # without skewing the tail percentiles we care about.
            self.samples.pop(len(self.samples) // 2)

    def percentile(self, pct: float) -> float:
        if not self.samples:
            return 0.0
        idx = min(len(self.samples) - 1, int(round((pct / 100.0) * (len(self.samples) - 1))))
        return round(self.samples[idx], 2)


class Metrics:
    """Thread-safe singleton-style metrics registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latencies: dict[str, _LatencyWindow] = defaultdict(_LatencyWindow)
        self._counters: dict[str, int] = defaultdict(int)

    # --- recording ----------------------------------------------------------
    def record_latency(self, endpoint: str, value_ms: float) -> None:
        with self._lock:
            self._latencies[endpoint].add(value_ms)

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    # --- convenience helpers ------------------------------------------------
    def record_cache_hit(self) -> None:
        self.incr("cache_hits")

    def record_cache_miss(self) -> None:
        self.incr("cache_misses")

    def record_db_read(self, amount: int = 1) -> None:
        self.incr("db_reads", amount)

    def record_db_write(self, amount: int = 1) -> None:
        self.incr("db_writes", amount)

    # --- reporting ----------------------------------------------------------
    def snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of all metrics."""
        with self._lock:
            hits = self._counters.get("cache_hits", 0)
            misses = self._counters.get("cache_misses", 0)
            total = hits + misses
            hit_rate = round(hits / total, 4) if total else 0.0

            latency_report = {
                endpoint: {
                    "p50_ms": window.percentile(50),
                    "p95_ms": window.percentile(95),
                    "count": len(window.samples),
                }
                for endpoint, window in self._latencies.items()
            }

            return {
                "latency": latency_report,
                "cache": {
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": hit_rate,
                },
                "database": {
                    "reads": self._counters.get("db_reads", 0),
                    "writes": self._counters.get("db_writes", 0),
                },
            }


# Module-level singleton shared across the app.
metrics = Metrics()
