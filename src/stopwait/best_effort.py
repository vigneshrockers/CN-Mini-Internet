"""One-shot sender used as the best-effort comparison baseline."""

from __future__ import annotations

import time

from .protocol import encode_packet
from .sender import TransferResult
from .udp_link import Pacer


def send_messages(link, run_id: str, messages: list[str], rate: float = 100.0) -> TransferResult:
    if not messages:
        raise ValueError("at least one message is required")
    started = time.monotonic()
    pacer = Pacer(rate)
    for seq, payload in enumerate(messages):
        pacer.wait()
        link.send(encode_packet("data", run_id, seq, len(messages), payload))
    return TransferResult(True, 0, time.monotonic() - started, None, len(messages))
