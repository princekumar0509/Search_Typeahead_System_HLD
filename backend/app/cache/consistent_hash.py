"""Consistent hashing ring with virtual nodes.

WHY CONSISTENT HASHING
----------------------
A naive sharding scheme such as ``node = hash(key) % N`` re-maps *almost every*
key when ``N`` changes (a node is added or removed). With 3 nodes, going to 4
re-maps ~75% of keys, causing a cache stampede against the database.

Consistent hashing places both nodes and keys on the same circular keyspace
(the "ring", here ``0 .. 2**32-1``). A key is owned by the first node found
walking clockwise from the key's hash. When a node is added or removed only the
keys between that node and its predecessor move — on average ``K / N`` keys —
instead of nearly all of them.

WHY VIRTUAL NODES
-----------------
With only one point per physical node, the keyspace is split unevenly and
removing a node dumps its entire range onto a single neighbour. By hashing each
physical node to many points ("virtual nodes" / replicas), the load is spread
smoothly and a node's keys are redistributed across *all* remaining nodes,
keeping balance within a few percent.
"""
from __future__ import annotations

import bisect
import hashlib
import logging

logger = logging.getLogger(__name__)


class ConsistentHashRing:
    """A consistent hash ring mapping arbitrary string keys to node names."""

    def __init__(self, nodes: list[str] | None = None, virtual_nodes: int = 150) -> None:
        """Initialise the ring.

        Args:
            nodes: initial physical node names to add.
            virtual_nodes: number of virtual points placed per physical node.
                Higher values give smoother balance at the cost of memory and
                slightly slower lookups.
        """
        self._virtual_nodes = virtual_nodes
        # Sorted list of virtual-node hash positions on the ring.
        self._ring_keys: list[int] = []
        # Map of ring position -> physical node name.
        self._ring: dict[int, str] = {}
        # Set of physical nodes currently on the ring.
        self._nodes: set[str] = set()

        for node in nodes or []:
            self.add_node(node)

    # --- hashing ------------------------------------------------------------
    @staticmethod
    def _hash(value: str) -> int:
        """Hash a string to a 32-bit point on the ring.

        MD5 is used purely as a fast, well-distributed (non-cryptographic here)
        hash; the security properties are irrelevant for sharding.
        """
        digest = hashlib.md5(value.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)  # take the top 32 bits

    def _vnode_key(self, node: str, replica: int) -> str:
        return f"{node}#vn{replica}"

    # --- membership ---------------------------------------------------------
    def add_node(self, node: str) -> None:
        """Add a physical node and its virtual replicas to the ring."""
        if node in self._nodes:
            logger.debug("Node %s already present on the ring", node)
            return

        self._nodes.add(node)
        for replica in range(self._virtual_nodes):
            position = self._hash(self._vnode_key(node, replica))
            # Skip the extremely rare collision rather than overwrite an owner.
            if position in self._ring:
                continue
            self._ring[position] = node
            bisect.insort(self._ring_keys, position)

        logger.info("Added node %s (%d virtual nodes). Ring size=%d",
                    node, self._virtual_nodes, len(self._ring_keys))

    def remove_node(self, node: str) -> None:
        """Remove a physical node and all of its virtual replicas."""
        if node not in self._nodes:
            logger.debug("Node %s not present; nothing to remove", node)
            return

        self._nodes.discard(node)
        positions_to_remove = [pos for pos, owner in self._ring.items() if owner == node]
        for position in positions_to_remove:
            del self._ring[position]
            index = bisect.bisect_left(self._ring_keys, position)
            if index < len(self._ring_keys) and self._ring_keys[index] == position:
                self._ring_keys.pop(index)

        logger.info("Removed node %s. Ring size=%d", node, len(self._ring_keys))

    # --- lookup -------------------------------------------------------------
    def get_node(self, key: str) -> str | None:
        """Return the node responsible for ``key``.

        Walks clockwise from the key's hash to the first virtual node, wrapping
        around the ring if necessary. Returns ``None`` if the ring is empty.
        """
        if not self._ring_keys:
            return None

        position = self._hash(key)
        # bisect_right gives the first virtual node strictly clockwise.
        index = bisect.bisect_right(self._ring_keys, position)
        if index == len(self._ring_keys):
            index = 0  # wrap around the ring
        return self._ring[self._ring_keys[index]]

    # --- introspection ------------------------------------------------------
    @property
    def nodes(self) -> list[str]:
        return sorted(self._nodes)

    def distribution(self, sample_keys: list[str]) -> dict[str, int]:
        """Return how many of ``sample_keys`` map to each node (for debugging)."""
        counts: dict[str, int] = {node: 0 for node in self._nodes}
        for key in sample_keys:
            owner = self.get_node(key)
            if owner is not None:
                counts[owner] += 1
        return counts
