"""Abstract provider protocols for meshcore-tools data sources."""

from typing import Protocol


class PacketProvider(Protocol):
    """Provides a stream of raw packet dicts from any source."""

    def fetch_packets(self, region: str, limit: int = 50) -> list[dict]:
        ...


class NodeProvider(Protocol):
    """Provides node metadata keyed by 64-char hex public key."""

    def fetch_nodes(self, region: str) -> dict[str, dict]:
        ...


class CoordProvider(Protocol):
    """Provides GPS coordinates keyed by 64-char hex public key."""

    def fetch_node_coords(self) -> dict[str, dict]:
        ...
