"""Local UDP demonstrations and repeated best-effort/stop-and-wait comparisons."""

from __future__ import annotations

import threading
import time
import uuid

from . import best_effort, sliding_window
from .metrics import TrialMetrics
from .receiver import Receiver
from .sender import TransferResult, send_messages as send_stop_wait
from .simulated_link import ImpairedUdpLink, ImpairmentPolicy
from .udp_link import UdpLink


def _local_pair(policy: ImpairmentPolicy, base_delay: float = 0.0):
    rx_raw = UdpLink(("127.0.0.1", 0))
    tx_raw = UdpLink(("127.0.0.1", 0), rx_raw.local_address)
    rx_raw.set_peer(tx_raw.local_address)
    tx = ImpairedUdpLink(tx_raw, policy, "sender_to_receiver", base_delay)
    rx = ImpairedUdpLink(rx_raw, policy, "receiver_to_sender", base_delay)
    return tx, rx


def run_trial(mode: str, loss_rate: float = 0.0, seed: int = 1,
              repetition: int = 1, count: int = 20, timeout: float = 0.15,
              max_retries: int = 5, rate: float = 100.0, window_size: int = 4,
              observation_timeout: float = 0.75, base_delay: float = 0.0,
              drop_once: tuple[str, str, int] | None = None,
              corrupt_once: tuple[str, str, int] | None = None,
              delay_once: tuple[str, str, int, float] | None = None,
              reachable: bool = True) -> TrialMetrics:
    run_id = str(uuid.uuid4())
    messages = [f"message-{seq:04d}" for seq in range(count)]
    policy = ImpairmentPolicy(loss_rate, seed, drop_once, corrupt_once, delay_once)
    if reachable:
        tx, rx = _local_pair(policy, base_delay)
        receiver = Receiver(rx, run_id, count, linger=max(0.4, timeout * (max_retries + 2)),
                            idle_timeout=max(5.0, observation_timeout + count / rate + base_delay * 2))
        thread = threading.Thread(target=receiver.run, daemon=True)
        thread.start()
    else:
        rx = None
        receiver = None
        thread = None
        sink = UdpLink(("127.0.0.1", 0))
        target = sink.local_address
        sink.close()
        tx_raw = UdpLink(("127.0.0.1", 0), target)
        tx = ImpairedUdpLink(tx_raw, policy, "sender_to_receiver", base_delay)

    started = time.monotonic()
    try:
        if mode == "best-effort":
            result = best_effort.send_messages(tx, run_id, messages, rate)
            if thread is not None:
                thread.join(observation_timeout)
                receiver.stop()
                thread.join(0.2)
            result.elapsed_seconds = time.monotonic() - started
        elif mode == "stop-and-wait":
            result = send_stop_wait(tx, run_id, messages, timeout, max_retries, rate)
            if thread is not None:
                thread.join(max(0.2, timeout * (max_retries + 2)))
                receiver.stop()
                thread.join(0.2)
        elif mode == "sliding-window":
            result = sliding_window.send_messages(tx, run_id, messages, window_size,
                                                  timeout, max_retries, rate)
            if thread is not None:
                thread.join(max(0.2, timeout * (max_retries + 2)))
                receiver.stop()
                thread.join(0.2)
        else:
            raise ValueError(f"unknown mode: {mode}")
    finally:
        tx.close()
        if rx is not None:
            rx.close()
    elapsed = time.monotonic() - started
    if result.elapsed_seconds == 0:
        result.elapsed_seconds = elapsed
    delivered = receiver.delivered if receiver else []
    return TrialMetrics.from_run(mode, loss_rate, repetition, result, delivered, count,
                                 receiver.invalid_packets if receiver else 0)


def run_required_evidence(count: int = 8) -> list[TrialMetrics]:
    return [
        run_trial("stop-and-wait", count=count, seed=1),
        run_trial("stop-and-wait", count=count, seed=2,
                  drop_once=("sender_to_receiver", "data", 2)),
        run_trial("stop-and-wait", count=count, seed=3,
                  drop_once=("receiver_to_sender", "ack", count - 1)),
        run_trial("stop-and-wait", count=count, seed=4,
                  corrupt_once=("sender_to_receiver", "data", 1)),
        run_trial("stop-and-wait", count=count, seed=5, reachable=False),
    ]


def run_comparison(repetitions: int = 3, count: int = 20, loss_levels=(0.0, 0.05),
                   rate: float = 100.0, base_delay: float = 0.01) -> list[TrialMetrics]:
    rows: list[TrialMetrics] = []
    for loss in loss_levels:
        for mode in ("best-effort", "stop-and-wait"):
            for repetition in range(1, repetitions + 1):
                seed = 1000 + repetition + int(loss * 10000) + (0 if mode == "best-effort" else 100)
                rows.append(run_trial(mode, loss, seed, repetition, count, rate=rate,
                                      observation_timeout=1.0, base_delay=base_delay))
    return rows


def run_reorder_demo(count: int = 8) -> TrialMetrics:
    return run_trial("sliding-window", count=count, timeout=0.25, window_size=4,
                     delay_once=("sender_to_receiver", "data", 0, 0.10))
