"""Stop-and-wait sender with per-message timeout and bounded retries."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .protocol import PacketError, decode_packet, encode_packet
from .udp_link import Pacer


@dataclass
class TransferResult:
    completed: bool
    retransmissions: int
    elapsed_seconds: float
    failed_sequence: int | None = None
    attempts: int = 0


def send_messages(link, run_id: str, messages: list[str], timeout: float = 0.25,
                  max_retries: int = 5, rate: float = 100.0) -> TransferResult:
    if not messages:
        raise ValueError("at least one message is required")
    if timeout <= 0 or max_retries < 0:
        raise ValueError("timeout must be positive and max_retries non-negative")
    started = time.monotonic()
    pacer = Pacer(rate)
    retries = 0
    attempts_total = 0
    total = len(messages)
    for seq, payload in enumerate(messages):
        acknowledged = False
        for attempt in range(max_retries + 1):
            pacer.wait()
            link.send(encode_packet("data", run_id, seq, total, payload))
            attempts_total += 1
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                raw = link.recv(remaining)
                if raw is None:
                    break
                try:
                    packet = decode_packet(raw)
                except PacketError:
                    continue
                if (packet["type"] == "ack" and packet["run_id"] == run_id
                        and packet["seq"] == seq and packet["total"] == total):
                    acknowledged = True
                    break
            if acknowledged:
                break
            if attempt < max_retries:
                retries += 1
        if not acknowledged:
            return TransferResult(False, retries, time.monotonic() - started, seq, attempts_total)
    return TransferResult(True, retries, time.monotonic() - started, None, attempts_total)
