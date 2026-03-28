"""map.meshcore.dev REST provider — implements CoordProvider."""

import urllib.request

import msgpack

_API_URL = "https://map.meshcore.dev/api/v1/nodes?binary=1&short=1"

_KEY_MAP = {
    "pk": "public_key",
    "n": "adv_name",
    "t": "type",
    "la": "last_advert",
    "id": "inserted_date",
    "ud": "updated_date",
    "p": "params",
    "l": "link",
    "s": "source",
}


class MeshcoreRestProvider:
    """REST client for map.meshcore.dev. Satisfies CoordProvider protocol."""

    def fetch_node_coords(self) -> dict[str, dict]:
        """Fetch node coordinates. Returns dict keyed by lowercase 64-char hex key."""
        req = urllib.request.Request(_API_URL)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = msgpack.unpackb(resp.read(), raw=False)

        coords: dict[str, dict] = {}
        nodes = data if isinstance(data, list) else data.get("nodes", [])
        for node in nodes:
            expanded = {_KEY_MAP.get(k, k): v for k, v in node.items()}
            key = expanded.get("public_key", "")
            if isinstance(key, bytes):
                key = key.hex()
            else:
                key = str(key).lower()
            if len(key) != 64:
                continue
            lat = expanded.get("lat")
            lon = expanded.get("lon")
            if lat is not None and lon is not None and (float(lat) != 0.0 or float(lon) != 0.0):
                coords[key] = {"lat": float(lat), "lon": float(lon)}
        return coords
