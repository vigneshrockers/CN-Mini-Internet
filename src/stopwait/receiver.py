"""Ordered, duplicate-safe receiver shared by stop-and-wait and window mode."""

from __future__ import annotations

import threading
import time

from .protocol import PacketError, decode_packet, encode_packet


class Receiver:
    def __init__(self, link, run_id: str, total: int, linger: float = 2.0, idle_timeout: float = 3.0):
        if total < 1:
            raise ValueError("total must be positive")
        self.link = link
        self.run_id = run_id
        self.total = total
        self.linger = max(0.0, linger)
        self.idle_timeout = max(0.1, idle_timeout)
        self.next_expected = 0
        self.buffer: dict[int, str] = {}
        self.delivered: list[str] = []
        self.invalid_packets = 0
        self.duplicate_packets = 0
        self.complete = False
        self._stop = threading.Event()
        self.started_at: float | None = None

    def stop(self) -> None:
        self._stop.set()

    def run(self, max_duration: float | None = None) -> None:
        self.started_at = time.monotonic()
        last_activity = self.started_at
        deadline = self.started_at + max_duration if max_duration is not None else None
        completed_at: float | None = None
        while not self._stop.is_set():
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            if completed_at is not None and now - completed_at >= self.linger:
                break
            if completed_at is None and now - last_activity >= self.idle_timeout:
                break
            timeout = 0.05
            if deadline is not None:
                timeout = min(timeout, max(0.0, deadline - now))
            raw = self.link.recv(timeout)
            if raw is None:
                continue
            try:
                packet = decode_packet(raw)
            except PacketError:
                self.invalid_packets += 1
                continue
            if packet["type"] != "data" or packet["run_id"] != self.run_id or packet["total"] != self.total:
                continue
            last_activity = time.monotonic()
            seq = packet["seq"]
            if seq < self.next_expected or seq in self.buffer:
                self.duplicate_packets += 1
            elif seq < self.total:
                self.buffer[seq] = packet["payload"]
            # ACK every valid in-range copy, including a duplicate. A duplicate final
            # packet can therefore recover a lost final ACK during the linger period.
            self.link.send(encode_packet("ack", self.run_id, seq, self.total))
            while self.next_expected in self.buffer:
                self.delivered.append(self.buffer.pop(self.next_expected))
                self.next_expected += 1
            if self.next_expected == self.total and completed_at is None:
                self.complete = True
                completed_at = time.monotonic()
