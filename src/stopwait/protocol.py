"""Packet encoding, validation, and IEEE CRC-32 protection."""

from __future__ import annotations

import json
import zlib
from typing import Any


class PacketError(ValueError):
    """Raised when a datagram is malformed or fails CRC validation."""


# Encode fields consistently so the sender and receiver calculate the same CRC.
def _canonical_bytes(fields: dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# Validate a packet, calculate its CRC-32, and serialize it as JSON bytes.
def encode_packet(packet_type: str, run_id: str, seq: int, total: int, payload: str = "") -> bytes:
    # Check required fields before building the serialized packet.
    if packet_type not in {"data", "ack"}:
        raise PacketError(f"unsupported packet type: {packet_type}")
    if not run_id or not isinstance(run_id, str):
        raise PacketError("run_id must be a non-empty string")
    if not isinstance(seq, int) or seq < 0:
        raise PacketError("seq must be a non-negative integer")
    if not isinstance(total, int) or total < 1 or seq >= total:
        raise PacketError("total must be positive and greater than seq")
    if packet_type == "data" and not isinstance(payload, str):
        raise PacketError("data payload must be a string")
    fields: dict[str, Any] = {
        "type": packet_type,
        "run_id": run_id,
        "seq": seq,
        "total": total,
    }
    if packet_type == "data":
        fields["payload"] = payload
    # The checksum covers the packet fields but not the checksum field itself.
    checksum = zlib.crc32(_canonical_bytes(fields)) & 0xFFFFFFFF
    packet = dict(fields)
    packet["crc32"] = f"{checksum:08x}"
    return _canonical_bytes(packet)


# Decode a datagram and reject it if its checksum or fields are invalid.
def decode_packet(datagram: bytes) -> dict[str, Any]:
    # Parse the JSON first so the checksum can be checked on its original fields.
    try:
        packet = json.loads(datagram.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError("datagram is not valid UTF-8 JSON") from exc
    if not isinstance(packet, dict):
        raise PacketError("packet must be a JSON object")
    checksum = packet.pop("crc32", None)
    if not isinstance(checksum, str) or len(checksum) != 8:
        raise PacketError("missing or malformed CRC-32")
    try:
        expected = int(checksum, 16)
    except ValueError as exc:
        raise PacketError("CRC-32 is not hexadecimal") from exc
    actual = zlib.crc32(_canonical_bytes(packet)) & 0xFFFFFFFF
    if actual != expected:
        raise PacketError("CRC-32 mismatch")
    # Validate packet meaning only after the CRC has been confirmed.
    packet_type = packet.get("type")
    run_id = packet.get("run_id")
    seq = packet.get("seq")
    total = packet.get("total")
    if packet_type not in {"data", "ack"} or not isinstance(run_id, str) or not run_id:
        raise PacketError("invalid packet type or run identifier")
    if not isinstance(seq, int) or seq < 0 or not isinstance(total, int) or total < 1 or seq >= total:
        raise PacketError("invalid sequence number or total")
    if packet_type == "data" and not isinstance(packet.get("payload"), str):
        raise PacketError("data packet has no string payload")
    if packet_type == "ack" and "payload" in packet:
        raise PacketError("ACK packet must not contain a payload")
    return packet
