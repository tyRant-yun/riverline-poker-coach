"""Project-owned append/read port for raw HandEventV1 envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from .contracts import HandEventV1


@dataclass(frozen=True, slots=True)
class RawHandEventV1:
    """A validated event together with the exact JSON string received at ingress."""

    event: HandEventV1
    raw_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.raw_json, str):
            raise TypeError("raw HandEventV1 JSON must be a string")
        if HandEventV1.model_validate_json(self.raw_json) != self.event:
            raise ValueError("event and raw_json must describe the same HandEventV1")

    @classmethod
    def from_json(cls, raw_json: str) -> RawHandEventV1:
        if not isinstance(raw_json, str):
            raise TypeError("raw HandEventV1 JSON must be a string")
        return cls(event=HandEventV1.model_validate_json(raw_json), raw_json=raw_json)

    @classmethod
    def from_event(cls, event: HandEventV1) -> RawHandEventV1:
        return cls(event=event, raw_json=event.to_json())


@dataclass(frozen=True, slots=True)
class HandEventAppendResult:
    hand_id: str
    previous_sequence: int
    appended_count: int
    last_sequence: int


class HandEventStoreError(RuntimeError):
    """Stable domain-facing base error; adapters do not expose driver errors."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class HandEventBatchError(HandEventStoreError):
    pass


class ExpectedSequenceConflict(HandEventStoreError):
    def __init__(self, *, hand_id: str, expected_sequence: int, actual_sequence: int):
        super().__init__(
            "expected_sequence_conflict",
            f"hand {hand_id!r} is at sequence {actual_sequence}, not expected {expected_sequence}",
        )
        self.hand_id = hand_id
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence


class HandEventIdentityConflict(HandEventStoreError):
    pass


class HandEventAppendRetryable(HandEventStoreError):
    pass


class HandEventStoreFailure(HandEventStoreError):
    pass


@runtime_checkable
class HandEventStore(Protocol):
    """Atomic optimistic append and ordered read boundary.

    ``expected_sequence`` is the highest sequence the caller believes is already
    durable before this append. A new hand therefore uses ``0`` and the first
    event in the batch must have sequence ``expected_sequence + 1``.
    """

    def append(
        self,
        *,
        hand_id: str,
        expected_sequence: int,
        events: Sequence[RawHandEventV1],
    ) -> HandEventAppendResult: ...

    def read(self, hand_id: str) -> tuple[RawHandEventV1, ...]: ...


def validate_append_batch(
    *,
    hand_id: str,
    expected_sequence: int,
    events: Sequence[RawHandEventV1],
) -> tuple[RawHandEventV1, ...]:
    """Validate adapter-independent batch invariants before opening a transaction."""

    if not hand_id:
        raise HandEventBatchError("invalid_hand_id", "hand_id must not be empty")
    if expected_sequence < 0:
        raise HandEventBatchError(
            "invalid_expected_sequence", "expected_sequence must be non-negative"
        )
    batch = tuple(events)
    if not batch:
        raise HandEventBatchError("empty_batch", "append requires at least one event")
    if any(item.event.hand_id != hand_id for item in batch):
        raise HandEventBatchError(
            "cross_hand_batch", "every event in a batch must match hand_id"
        )
    event_ids = [item.event.event_id for item in batch]
    if len(event_ids) != len(set(event_ids)):
        raise HandEventBatchError(
            "duplicate_event_id_in_batch", "event_id values must be unique within a batch"
        )
    expected_sequences = list(
        range(expected_sequence + 1, expected_sequence + len(batch) + 1)
    )
    actual_sequences = [item.event.sequence for item in batch]
    if actual_sequences != expected_sequences:
        raise HandEventBatchError(
            "non_contiguous_batch",
            "batch sequences must be ordered and contiguous from expected_sequence + 1",
        )
    return batch


__all__ = [
    "ExpectedSequenceConflict",
    "HandEventAppendResult",
    "HandEventAppendRetryable",
    "HandEventBatchError",
    "HandEventIdentityConflict",
    "HandEventStore",
    "HandEventStoreError",
    "HandEventStoreFailure",
    "RawHandEventV1",
]
