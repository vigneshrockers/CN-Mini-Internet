"""One-shot sender used as the best-effort comparison baseline."""

from __future__ import annotations

import time

from .protocol import encode_packet
from .sender import TransferResult
from .udp_link import Pacer


# Send each message once without waiting for acknowledgments.
def send_messages(link, run_id: str, messages: list[str], rate: float = 100.0) -> TransferResult:
    # Reject an empty transfer before creating timing or pacing state.
    if not messages:
        raise ValueError("at least one message is required")
    started = time.monotonic()
    pacer = Pacer(rate)
    # Send in sequence, but do not wait for acknowledgments or retransmit.
    for seq, payload in enumerate(messages):
        pacer.wait()
        link.send(encode_packet("data", run_id, seq, len(messages), payload))
    # Report that all messages were sent, not that the receiver got them.
    return TransferResult(True, 0, time.monotonic() - started, None, len(messages))
