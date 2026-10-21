"""Small UDP datagram endpoint used by all transfer modes."""

from __future__ import annotations

import socket
import time


class UdpLink:
    # Bind a UDP socket and save its optional destination endpoint.
    def __init__(self, local: tuple[str, int], peer: tuple[str, int] | None = None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(local)
        self.peer = peer

    # Return the actual address and port assigned to this socket.
    @property
    def local_address(self) -> tuple[str, int]:
        host, port = self.socket.getsockname()[:2]
        return str(host), int(port)

    # Set the destination used by later send calls.
    def set_peer(self, peer: tuple[str, int]) -> None:
        self.peer = peer

    # Send one datagram to the configured peer.
    def send(self, datagram: bytes) -> None:
        if self.peer is None:
            raise RuntimeError("UDP peer address has not been configured")
        self.socket.sendto(datagram, self.peer)

    # Wait for a datagram, treating Windows reset errors as lost responses.
    def recv(self, timeout: float) -> bytes | None:
        # Keep one deadline even if the socket reports a reset and retries.
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

    # Release the UDP socket.
    def close(self) -> None:
        self.socket.close()

    # Let a UdpLink be used in a with statement.
    def __enter__(self) -> "UdpLink":
        return self

    # Close the socket when its with statement ends.
    def __exit__(self, *_: object) -> None:
        self.close()


class Pacer:
    """Limits data-datagram sends to a configured maximum packets per second."""

    # Calculate the minimum time between consecutive sends.
    def __init__(self, max_packets_per_second: float):
        if max_packets_per_second <= 0:
            raise ValueError("rate must be greater than zero")
        self.interval = 1.0 / max_packets_per_second
        self.next_send = 0.0

    # Pause when needed to stay within the configured send rate.
    def wait(self) -> None:
        now = time.monotonic()
        if self.next_send > now:
            time.sleep(self.next_send - now)
        self.next_send = max(self.next_send, time.monotonic()) + self.interval
