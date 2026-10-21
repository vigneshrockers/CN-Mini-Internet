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

    @classmethod
    def from_run(cls, mode: str, loss_rate: float, repetition: int,
                 result: TransferResult, delivered: list[str], total: int,
                 invalid_packets: int = 0) -> "TrialMetrics":
        unique = len(delivered)
        return cls(mode, loss_rate, repetition, unique, total,
                   unique / total if total else 0.0,
                   result.completed and unique == total,
                   result.retransmissions, result.elapsed_seconds, invalid_packets)

    def as_dict(self) -> dict:
        return asdict(self)
