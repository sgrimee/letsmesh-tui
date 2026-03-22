"""Tests for lma.decoder.decode_packet."""

import struct

from lma.decoder import decode_packet


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------

def _header(route_type: int, payload_type: int, version: int = 0) -> int:
    return (version << 6) | (payload_type << 2) | route_type


def _flood_ack(payload: bytes = b"\xaa\xbb") -> bytes:
    """Flood + Ack, no hops."""
    header = _header(route_type=0x01, payload_type=0x03)  # Flood + Ack
    path_byte = 0x00  # hash_size=1, 0 hops
    return bytes([header, path_byte]) + payload


def _flood_textmsg(dest: bytes, src: bytes, hops: tuple[bytes, ...] | list[bytes] = ()) -> bytes:
    """Flood + TextMessage with optional relay hops."""
    header = _header(route_type=0x01, payload_type=0x02)  # Flood + TextMessage
    hop_count = len(hops)
    hash_size = len(hops[0]) if hops else 4
    path_byte = ((hash_size - 1) << 6) | hop_count
    path_data = b"".join(hops)
    payload = dest + src + b"\x00\x00" + b"\xff" * 8  # mac + fake ciphertext
    return bytes([header, path_byte]) + path_data + payload


def _advert_packet(pub_key: bytes, lat: float | None = None, lon: float | None = None,
                   name: str | None = None, role: int = 1) -> bytes:
    """Flood + Advert with optional location and name."""
    header = _header(route_type=0x01, payload_type=0x04)  # Flood + Advert
    path_byte = 0x00  # hash_size=1, 0 hops

    timestamp = struct.pack("<I", 0x12345678)
    signature = b"\x00" * 64

    flags = role & 0x0F
    if lat is not None and lon is not None:
        flags |= 0x10  # HasLocation
    if name is not None:
        flags |= 0x80  # HasName

    payload = pub_key[:32] + timestamp + signature + bytes([flags])
    if lat is not None and lon is not None:
        payload += struct.pack("<i", int(lat * 1_000_000))
        payload += struct.pack("<i", int(lon * 1_000_000))
    if name is not None:
        payload += name.encode() + b"\x00"

    return bytes([header, path_byte]) + payload


# ---------------------------------------------------------------------------
# Tests — error paths
# ---------------------------------------------------------------------------

def test_decode_empty():
    result = decode_packet("")
    assert "error" in result


def test_decode_invalid_hex():
    result = decode_packet("zzzz")
    assert result == {"error": "Invalid hex data"}


def test_decode_too_short():
    result = decode_packet("0a")
    assert "error" in result


# ---------------------------------------------------------------------------
# Tests — Flood + Ack
# ---------------------------------------------------------------------------

def test_decode_flood_ack_route_type():
    result = decode_packet(_flood_ack().hex())
    assert result["route_type"] == "Flood"


def test_decode_flood_ack_payload_type():
    result = decode_packet(_flood_ack().hex())
    assert result["payload_type"] == "Ack"


def test_decode_flood_ack_no_hops():
    result = decode_packet(_flood_ack().hex())
    assert result["path"] == []


def test_decode_flood_ack_version():
    result = decode_packet(_flood_ack().hex())
    assert result["payload_version"] == 0


# ---------------------------------------------------------------------------
# Tests — Flood + TextMessage
# ---------------------------------------------------------------------------

def test_decode_textmsg_hashes():
    dest = bytes([0xDE])
    src = bytes([0xCA])
    packet = _flood_textmsg(dest, src)
    result = decode_packet(packet.hex())
    assert result["payload_type"] == "TextMessage"
    assert result["decoded"]["dest_hash"] == "de"
    assert result["decoded"]["src_hash"] == "ca"
    assert result["decoded"]["encrypted"] is True


def test_decode_textmsg_with_hops():
    hop1 = bytes([0xAA, 0xBB, 0xCC, 0xDD])
    hop2 = bytes([0x11, 0x22, 0x33, 0x44])
    dest = bytes([0xDE])
    src = bytes([0xCA])
    packet = _flood_textmsg(dest, src, hops=[hop1, hop2])
    result = decode_packet(packet.hex())
    assert len(result["path"]) == 2
    assert result["path"][0] == "aabbccdd"
    assert result["path"][1] == "11223344"


# ---------------------------------------------------------------------------
# Tests — Flood + Advert
# ---------------------------------------------------------------------------

def test_decode_advert_pubkey():
    pub = bytes(range(32))
    packet = _advert_packet(pub)
    result = decode_packet(packet.hex())
    assert result["payload_type"] == "Advert"
    assert result["decoded"]["public_key"] == pub.hex()


def test_decode_advert_with_location():
    pub = b"\x01" * 32
    packet = _advert_packet(pub, lat=49.5, lon=6.2)
    result = decode_packet(packet.hex())
    dec = result["decoded"]
    assert abs(dec["lat"] - 49.5) < 0.0001
    assert abs(dec["lon"] - 6.2) < 0.0001


def test_decode_advert_without_location():
    pub = b"\x02" * 32
    packet = _advert_packet(pub)
    result = decode_packet(packet.hex())
    assert "lat" not in result["decoded"]
    assert "lon" not in result["decoded"]


def test_decode_advert_with_name():
    pub = b"\x03" * 32
    packet = _advert_packet(pub, name="my-node")
    result = decode_packet(packet.hex())
    assert result["decoded"]["name"] == "my-node"


def test_decode_advert_role():
    pub = b"\x04" * 32
    packet = _advert_packet(pub, role=2)  # Repeater
    result = decode_packet(packet.hex())
    assert result["decoded"]["role"] == "Repeater"
