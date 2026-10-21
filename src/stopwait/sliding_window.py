"""Optional selective-repeat sliding-window sender."""

from __future__ import annotations

import time

from .protocol import PacketError, decode_packet, encode_packet
from .sender import TransferResult
from .udp_link import Pacer


def send_messages(link, run_id: str, messages: list[str], window_size: int = 4,
                  timeout: float = 0.25, max_retries: int = 5,
                  rate: float = 100.0) -> TransferResult:
    if not messages or window_size < 1 or timeout <= 0 or max_retries < 0:
        raise ValueError("messages, window size, timeout, and retry limit are invalid")
    started = time.monotonic()
    total = len(messages)
    base = 0
    next_to_send = 0
    acked: set[int] = set()
    attempts: dict[int, int] = {}
    sent_at: dict[int, float] = {}
    retransmissions = 0
    attempts_total = 0
    pacer = Pacer(rate)

    while base < total:
        while next_to_send < total and next_to_send < base + window_size:
            pacer.wait()
            link.send(encode_packet("data", run_id, next_to_send, total, messages[next_to_send]))
            attempts[next_to_send] = 1
            sent_at[next_to_send] = time.monotonic()
            attempts_total += 1
            next_to_send += 1

        now = time.monotonic()
        expired = [seq for seq in range(base, next_to_send)
                   if seq not in acked and now - sent_at[seq] >= timeout]
        for seq in expired:
            if attempts[seq] >= max_retries + 1:
                return TransferResult(False, retransmissions, now - started, seq, attempts_total)
            pacer.wait()
            link.send(encode_packet("data", run_id, seq, total, messages[seq]))
            attempts[seq] += 1
            sent_at[seq] = time.monotonic()
            attempts_total += 1
            retransmissions += 1

        pending_times = [sent_at[seq] + timeout for seq in range(base, next_to_send) if seq not in acked]
        wait_for = max(0.0, min(pending_times) - time.monotonic()) if pending_times else 0.05
        raw = link.recv(min(wait_for, 0.05))
        if raw is None:
            continue
        try:
            packet = decode_packet(raw)
        except PacketError:
            continue
        if packet["type"] == "ack" and packet["run_id"] == run_id and packet["total"] == total:
            seq = packet["seq"]
            if base <= seq < next_to_send:
                acked.add(seq)
                while base in acked:
                    acked.remove(base)
                    sent_at.pop(base, None)
                    attempts.pop(base, None)
                    base += 1
    return TransferResult(True, retransmissions, time.monotonic() - started, None, attempts_total)
