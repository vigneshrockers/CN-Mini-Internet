"""Virtual mini-internet packet encoding with IEEE CRC-32."""
from __future__ import annotations
import base64
import json
import zlib
from dataclasses import dataclass
from typing import Any
MAX_DATAGRAM = 1200
VALID_TYPES = {'PROBE', 'ECHO', 'DATA', 'ACK', 'ERROR'}

class PacketError(ValueError):
    """Malformed, oversized, or corrupted virtual packet."""

def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

@dataclass(frozen=True)
class Packet:
    source: str
    destination: str
    hop_limit: int
    message_type: str
    message_id: str
    payload: bytes = b''

    def encode(self) -> bytes:
        if not self.source or not self.destination or (not self.message_id):
            raise PacketError('source, destination, and message_id must be non-empty')
        if not 0 <= self.hop_limit <= 255:
            raise PacketError('hop_limit must be between 0 and 255')
        if self.message_type not in VALID_TYPES:
            raise PacketError(f'unsupported message type: {self.message_type}')
        fields = {'source': self.source, 'destination': self.destination, 'hop_limit': self.hop_limit, 'message_type': self.message_type, 'message_id': self.message_id, 'payload': base64.b64encode(self.payload).decode('ascii')}
        fields['crc32'] = f'{zlib.crc32(_canonical(fields)) & 4294967295:08x}'
        result = _canonical(fields)
        if len(result) > MAX_DATAGRAM:
            raise PacketError(f'serialized packet is {len(result)} bytes; maximum is {MAX_DATAGRAM}')
        return result

    @classmethod
    def decode(cls, datagram: bytes) -> 'Packet':
        if len(datagram) > MAX_DATAGRAM:
            raise PacketError(f'datagram exceeds {MAX_DATAGRAM} bytes')
        try:
            fields = json.loads(datagram.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PacketError('datagram is not valid UTF-8 JSON') from exc
        if not isinstance(fields, dict):
            raise PacketError('packet must be a JSON object')
        checksum = fields.pop('crc32', None)
        if not isinstance(checksum, str) or len(checksum) != 8:
            raise PacketError('missing or malformed CRC-32')
        try:
            expected = int(checksum, 16)
        except ValueError as exc:
            raise PacketError('CRC-32 is not hexadecimal') from exc
        if zlib.crc32(_canonical(fields)) & 4294967295 != expected:
            raise PacketError('CRC-32 mismatch')
        required = {'source', 'destination', 'hop_limit', 'message_type', 'message_id', 'payload'}
        if set(fields) != required:
            raise PacketError('packet fields are missing or unexpected')
        if not all((isinstance(fields[k], str) and fields[k] for k in ('source', 'destination', 'message_id'))):
            raise PacketError('source, destination, and message_id must be non-empty strings')
        if type(fields['hop_limit']) is not int or not 0 <= fields['hop_limit'] <= 255:
            raise PacketError('invalid hop_limit')
        if fields['message_type'] not in VALID_TYPES:
            raise PacketError('invalid message_type')
        try:
            payload = base64.b64decode(fields['payload'], validate=True)
        except (ValueError, TypeError) as exc:
            raise PacketError('payload is not valid base64') from exc
        return cls(fields['source'], fields['destination'], fields['hop_limit'], fields['message_type'], fields['message_id'], payload)
