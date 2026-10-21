"""Comparison result helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .sender import TransferResult


@dataclass
class TrialMetrics:
    mode: str
    loss_rate: float
    repetition: int
    unique_delivered: int
    total_messages: int
    delivery_fraction: float
    complete: bool
    retransmissions: int
    elapsed_seconds: float
    invalid_packets: int

    # Convert one transfer run and its receiver results into summary metrics.
    @classmethod
    def from_run(cls, mode: str, loss_rate: float, repetition: int,
                 result: TransferResult, delivered: list[str], total: int,
                 invalid_packets: int = 0) -> "TrialMetrics":
        # Count unique messages so duplicates do not improve the score.
        unique = len(delivered)
        # Mark complete only when sender status and receiver delivery both agree.
        return cls(mode, loss_rate, repetition, unique, total,
                   unique / total if total else 0.0,
                   result.completed and unique == total,
                   result.retransmissions, result.elapsed_seconds, invalid_packets)

    # Return the metric fields in a form that can be printed as JSON.
    def as_dict(self) -> dict:
        return asdict(self)
