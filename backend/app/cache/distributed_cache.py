"""Distributed cache facade.

Ties together the :class:`ConsistentHashRing` and a set of :class:`CacheNode`
instances. Callers interact with this single object as if it were one cache;
internally each key is routed to the responsible node via consistent hashing.
"""
from __future__ import annotations

import logging
from typing import Any

from app.cache.cache_node import CacheNode
from app.cache.consistent_hash import ConsistentHashRing

logger = logging.getLogger(__name__)


class DistributedCache:
    """A sharded cache fronted by a consistent hash ring."""

    def __init__(self, node_names: list[str], virtual_nodes: int = 150, default_ttl: int = 60) -> None:
        self._default_ttl = default_ttl
        self._ring = ConsistentHashRing(nodes=node_names, virtual_nodes=virtual_nodes)
        self._nodes: dict[str, CacheNode] = {name: CacheNode(name) for name in node_names}
        logger.info("DistributedCache initialised with nodes=%s", node_names)

    # --- routing ------------------------------------------------------------
    def get_node_name(self, key: str) -> str:
        """Return the name of the node responsible for ``key``."""
        node = self._ring.get_node(key)
        if node is None:
            raise RuntimeError("Cache ring has no nodes configured")
        return node

    def _node_for(self, key: str) -> CacheNode:
        return self._nodes[self.get_node_name(key)]

    # --- operations ---------------------------------------------------------
    def get(self, key: str) -> tuple[bool, Any]:
        """Return ``(hit, value)`` for ``key`` from its responsible node."""
        return self._node_for(key).get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Cache ``value`` under ``key`` with the given (or default) TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._node_for(key).set(key, value, ttl)

    def invalidate(self, key: str) -> bool:
        """Invalidate ``key`` on its responsible node."""
        return self._node_for(key).invalidate(key)

    def ttl_remaining(self, key: str) -> int:
        return self._node_for(key).ttl_remaining(key)

    def is_hit(self, key: str) -> bool:
        hit, _ = self._node_for(key).get(key)
        return hit

    # --- topology management ------------------------------------------------
    def add_node(self, name: str) -> None:
        if name not in self._nodes:
            self._nodes[name] = CacheNode(name)
        self._ring.add_node(name)

    def remove_node(self, name: str) -> None:
        self._ring.remove_node(name)
        self._nodes.pop(name, None)

    # --- introspection ------------------------------------------------------
    @property
    def ring(self) -> ConsistentHashRing:
        return self._ring

    def stats(self) -> dict[str, int]:
        """Return the number of live entries per node."""
        return {name: node.size() for name, node in self._nodes.items()}
