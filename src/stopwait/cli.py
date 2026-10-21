"""Command-line interface for demonstrations and two-endpoint operation."""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid

from . import best_effort, sliding_window
from .receiver import Receiver
from .scenarios import run_comparison, run_reorder_demo, run_required_evidence
from .sender import send_messages as send_stop_wait
from .udp_link import UdpLink


# Build the numbered messages used by the sender demonstrations.
def _messages(count: int) -> list[str]:
    return [f"message-{seq:04d}" for seq in range(count)]


# Print each trial result as one JSON line.
def _print_rows(rows) -> None:
    for row in rows:
        print(json.dumps(row.as_dict(), sort_keys=True))


# Set up the existing command names and their command-line options.
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UDP transfer protocol demonstrations")
    sub = parser.add_subparsers(dest="command", required=True)
    # These commands run the scripted evidence, comparison, and reorder cases.
    demo = sub.add_parser("evidence", help="run required loss, corruption, and bounded-failure cases")
    demo.add_argument("--count", type=int, default=8)
    compare = sub.add_parser("compare", help="repeat best-effort vs stop-and-wait comparison")
    compare.add_argument("--count", type=int, default=20)
    compare.add_argument("--repetitions", type=int, default=3)
    compare.add_argument("--rate", type=float, default=100.0)
    compare.add_argument("--delay", type=float, default=0.01)
    reorder = sub.add_parser("reorder-demo", help="run optional sliding-window reordering demo")
    reorder.add_argument("--count", type=int, default=8)
    # The endpoint commands support running sender and receiver in separate windows.
    receive = sub.add_parser("receive", help="listen for one UDP transfer")
    receive.add_argument("--host", default="0.0.0.0")
    receive.add_argument("--port", type=int, required=True)
    receive.add_argument("--peer-host", required=True)
    receive.add_argument("--peer-port", type=int, required=True)
    receive.add_argument("--run-id", required=True)
    receive.add_argument("--count", type=int, required=True)
    receive.add_argument("--linger", type=float, default=3.0)
    receive.add_argument("--idle-timeout", type=float, default=10.0)
    send = sub.add_parser("send", help="send generated messages to a UDP receiver")
    send.add_argument("--host", default="0.0.0.0")
    send.add_argument("--port", type=int, default=0)
    send.add_argument("--peer-host", required=True)
    send.add_argument("--peer-port", type=int, required=True)
    send.add_argument("--count", type=int, default=20)
    send.add_argument("--run-id", default=None)
    send.add_argument("--mode", choices=("best-effort", "stop-and-wait", "sliding-window"), default="stop-and-wait")
    send.add_argument("--window-size", type=int, default=4)
    send.add_argument("--timeout", type=float, default=0.25)
    send.add_argument("--retries", type=int, default=5)
    send.add_argument("--rate", type=float, default=100.0)
    send.add_argument("--observation-timeout", type=float, default=1.0)
    return parser


# Run the selected transfer demo or endpoint command.
def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Return failure if a required evidence case does not recover as expected.
    if args.command == "evidence":
        rows = run_required_evidence(args.count)
        _print_rows(rows)
        return 0 if all(row.complete for row in rows[:4]) and not rows[4].complete else 1
    if args.command == "compare":
        _print_rows(run_comparison(args.repetitions, args.count, rate=args.rate, base_delay=args.delay))
        return 0
    if args.command == "reorder-demo":
        row = run_reorder_demo(args.count)
        _print_rows([row])
        return 0 if row.complete else 1
    if args.command == "receive":
        raw = UdpLink((args.host, args.port), (args.peer_host, args.peer_port))
        receiver = Receiver(raw, args.run_id, args.count, args.linger, args.idle_timeout)
        receiver.run()
        print(json.dumps({"complete": receiver.complete, "delivered": receiver.delivered,
                          "invalid_packets": receiver.invalid_packets,
                          "duplicates": receiver.duplicate_packets}))
        raw.close()
        return 0 if receiver.complete else 1
    if args.command == "send":
        run_id = args.run_id or str(uuid.uuid4())
        raw = UdpLink((args.host, args.port), (args.peer_host, args.peer_port))
        messages = _messages(args.count)
        try:
            # Reuse the same link setup while selecting the requested sender mode.
            if args.mode == "best-effort":
                result = best_effort.send_messages(raw, run_id, messages, args.rate)
                time.sleep(args.observation_timeout)
            elif args.mode == "sliding-window":
                result = sliding_window.send_messages(raw, run_id, messages, args.window_size,
                                                      args.timeout, args.retries, args.rate)
            else:
                result = send_stop_wait(raw, run_id, messages, args.timeout, args.retries, args.rate)
            print(json.dumps({"run_id": run_id, "sender_finished": result.completed,
                              "delivery_confirmed": None if args.mode == "best-effort" else result.completed,
                              "retransmissions": result.retransmissions,
                              "elapsed_seconds": result.elapsed_seconds,
                              "failed_sequence": result.failed_sequence,
                              "attempts": result.attempts}))
            return 0 if result.completed else 2
        finally:
            raw.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
