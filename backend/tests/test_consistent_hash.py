"""Tests for the consistent hash ring.

Run with:  pytest backend/tests/test_consistent_hash.py
These tests verify the two core guarantees: even distribution with virtual
nodes, and minimal key movement when a node is removed.
"""
from __future__ import annotations

from app.cache.consistent_hash import ConsistentHashRing


def _sample_keys(n: int) -> list[str]:
    return [f"suggest:prefix-{i}" for i in range(n)]


def test_keys_map_consistently() -> None:
    ring = ConsistentHashRing(nodes=["node1", "node2", "node3"], virtual_nodes=150)
    keys = _sample_keys(1000)
    first = {k: ring.get_node(k) for k in keys}
    # Same key -> same node on repeated lookups.
    assert all(ring.get_node(k) == first[k] for k in keys)


def test_distribution_is_reasonably_balanced() -> None:
    ring = ConsistentHashRing(nodes=["node1", "node2", "node3"], virtual_nodes=200)
    dist = ring.distribution(_sample_keys(9000))
    # Each node should hold roughly a third; allow generous slack.
    for count in dist.values():
        assert 2000 < count < 4000


def test_minimal_movement_on_node_removal() -> None:
    ring = ConsistentHashRing(nodes=["node1", "node2", "node3"], virtual_nodes=200)
    keys = _sample_keys(9000)
    before = {k: ring.get_node(k) for k in keys}

    ring.remove_node("node2")
    after = {k: ring.get_node(k) for k in keys}

    moved = sum(1 for k in keys if before[k] != after[k])
    # Only keys previously owned by node2 should move (~1/3); definitely far
    # below the ~2/3 that naive modulo hashing would shuffle.
    assert moved < len(keys) * 0.45
    # Keys not on node2 stay put.
    for k in keys:
        if before[k] != "node2":
            assert after[k] == before[k]
