"""Small UDP datagram endpoint used by all transfer modes."""

from __future__ import annotations

import socket
import time


class UdpLink:
    def __init__(self, local: tuple[str, int], peer: tuple[str, int] | None = None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(local)
        self.peer = peer

    @property
    def local_address(self) -> tuple[str, int]:
        host, port = self.socket.getsockname()[:2]
        return str(host), int(port)

    def set_peer(self, peer: tuple[str, int]) -> None:
        self.peer = peer

    def send(self, datagram: bytes) -> None:
        if self.peer is None:
            raise RuntimeError("UDP peer address has not been configured")
        self.socket.sendto(datagram, self.peer)

    def recv(self, timeout: float) -> bytes | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.socket.settimeout(remaining)
            try:
                data, _address = self.socket.recvfrom(65507)
                return data
            except socket.timeout:
                return None
            except ConnectionResetError:
                # Windows may report UDP ICMP Port Unreachable as WSAECONNRESET.
                # Treat it as a lost response and preserve the caller's timeout.
                continue

    def close(self) -> None:
        self.socket.close()

    def __enter__(self) -> "UdpLink":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class Pacer:
    """Limits data-datagram sends to a configured maximum packets per second."""

    def __init__(self, max_packets_per_second: float):
        if max_packets_per_second <= 0:
            raise ValueError("rate must be greater than zero")
        self.interval = 1.0 / max_packets_per_second
        self.next_send = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if self.next_send > now:
            time.sleep(self.next_send - now)
        self.next_send = max(self.next_send, time.monotonic()) + self.interval
