"""Deterministic and random UDP loss, delay, and corruption for experiments."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from .protocol import PacketError, decode_packet


@dataclass
class ImpairmentPolicy:
    loss_rate: float = 0.0
    seed: int = 1
    drop_once: tuple[str, str, int] | None = None
    corrupt_once: tuple[str, str, int] | None = None
    delay_once: tuple[str, str, int, float] | None = None
    _random: random.Random = field(init=False, repr=False)
    _used: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # Check the loss setting and create a repeatable random-number generator.
    def __post_init__(self) -> None:
        if not 0 <= self.loss_rate < 1:
            raise ValueError("loss rate must be in [0, 1)")
        self._random = random.Random(self.seed)

    # Choose a one-time or random impairment for this datagram.
    def action(self, direction: str, datagram: bytes) -> tuple[str, float]:
        try:
            packet = decode_packet(datagram)
            packet_type, seq = str(packet["type"]), int(packet["seq"])
        except (PacketError, KeyError, TypeError, ValueError):
            packet_type, seq = "unknown", -1
        key = (direction, packet_type, seq)
        with self._lock:
            # Apply each targeted test impairment at most once per trial.
            if self.drop_once == key and "drop" not in self._used:
                self._used.add("drop")
                return "drop", 0.0
            if self.corrupt_once == key and "corrupt" not in self._used:
                self._used.add("corrupt")
                return "corrupt", 0.0
            if self.delay_once and self.delay_once[:3] == key and "delay" not in self._used:
                self._used.add("delay")
                return "delay", self.delay_once[3]
            # Use the seeded generator for repeatable random-loss trials.
            if self._random.random() < self.loss_rate:
                return "drop", 0.0
        return "send", 0.0


class ImpairedUdpLink:
    """Wraps a UdpLink. Directions are sender_to_receiver or receiver_to_sender."""

    # Save the impairment settings that apply to this direction of travel.
    def __init__(self, link, policy: ImpairmentPolicy, direction: str, base_delay: float = 0.0):
        if direction not in {"sender_to_receiver", "receiver_to_sender"}:
            raise ValueError("invalid link direction")
        self.link = link
        self.policy = policy
        self.direction = direction
        self.base_delay = max(0.0, base_delay)
        self._timers: list[threading.Timer] = []
        self._lock = threading.Lock()

    # Apply the selected drop, corruption, or delay before sending.
    def send(self, datagram: bytes) -> None:
        action, extra_delay = self.policy.action(self.direction, datagram)
        if action == "drop":
            return
        outgoing = datagram
        if action == "corrupt" and outgoing:
            # Flip one bit so the receiver's CRC check can detect the change.
            damaged = bytearray(outgoing)
            damaged[len(damaged) // 2] ^= 0x01
            outgoing = bytes(damaged)
        delay = self.base_delay + extra_delay
        if extra_delay > 0:
            # A timer schedules this one-off delay without blocking receives.
            timer = threading.Timer(delay, self.link.send, args=(outgoing,))
            timer.daemon = True
            with self._lock:
                self._timers.append(timer)
            timer.start()
        elif delay > 0:
            time.sleep(delay)
            self.link.send(outgoing)
        else:
            self.link.send(outgoing)

    # Pass receive calls through to the underlying UDP link.
    def recv(self, timeout: float) -> bytes | None:
        return self.link.recv(timeout)

    # Cancel delayed sends and close the underlying socket.
    def close(self) -> None:
        with self._lock:
            for timer in self._timers:
                timer.cancel()
        self.link.close()
