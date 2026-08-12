"""Versioned recovery contracts and runner over durable HandEventV1 streams."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Protocol, runtime_checkable

from pydantic import AwareDatetime, Field, JsonValue, StrictInt, model_validator

from .contracts import HandEventV1, SimulatorContractV1

if TYPE_CHECKING:
    from .event_store import HandEventStore


class ProjectionIdentityV1(SimulatorContractV1):
    """Stable identity for one independently rebuildable projector version."""

    projection_name: str = Field(min_length=1, max_length=128)
    projection_version: Annotated[StrictInt, Field(ge=1)]


class OutboxIntentV1(SimulatorContractV1):
    """Durable intent whose key must also identify the external side effect."""

    message_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    topic: str = Field(min_length=1, max_length=128)
    payload: dict[str, JsonValue]

    @classmethod
    def for_event(
        cls,
        *,
        event_id: str,
        purpose: str,
        topic: str,
        payload: dict[str, JsonValue],
    ) -> OutboxIntentV1:
        if not event_id:
            raise ValueError("event_id must not be empty")
        if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", purpose) is None:
            raise ValueError(
                "purpose must be a lowercase token containing only letters, digits, _, . or -"
            )
        idempotency_key = f"{event_id}:{purpose}"
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return cls(
            message_id=f"outbox-{digest}",
            idempotency_key=idempotency_key,
            topic=topic,
            payload=payload,
        )


class OutboxStatusV1(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DISPATCHED = "dispatched"


class OutboxMessageV1(OutboxIntentV1):
    """Durable claim state; dispatchers must pass idempotency_key downstream."""

    status: OutboxStatusV1 = OutboxStatusV1.PENDING
    attempt_count: Annotated[StrictInt, Field(ge=0)] = 0
    available_at: AwareDatetime
    claimed_by: str | None = Field(default=None, min_length=1, max_length=128)
    lease_expires_at: AwareDatetime | None = None
    last_error: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_claim_state(self) -> OutboxMessageV1:
        claimed = self.claimed_by is not None or self.lease_expires_at is not None
        if self.status is OutboxStatusV1.PROCESSING:
            if self.claimed_by is None or self.lease_expires_at is None:
                raise ValueError("processing messages require a worker and lease")
        elif claimed:
            raise ValueError("only processing messages may carry claim state")
        return self


class ProjectionCheckpointV1(SimulatorContractV1):
    """Durable monotonic position for one projector and event stream."""

    projection_identity: ProjectionIdentityV1
    stream_id: str = Field(min_length=1, max_length=128)
    last_sequence: Annotated[StrictInt, Field(ge=0)] = 0
    last_event_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_position(self) -> ProjectionCheckpointV1:
        if (self.last_sequence == 0) != (self.last_event_id is None):
            raise ValueError("sequence zero and a missing event id must appear together")
        return self


class ProjectionSnapshotV1(SimulatorContractV1):
    """Disposable read-model cache derived from a durable event prefix."""

    projection_identity: ProjectionIdentityV1
    stream_id: str = Field(min_length=1, max_length=128)
    sequence: Annotated[StrictInt, Field(ge=1)]
    event_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, JsonValue]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProjectionSequenceError(ProjectionError):
    pass


class ProjectionNeedsRebuild(ProjectionError):
    pass


class ProjectionStoreFailure(ProjectionError):
    pass


@runtime_checkable
class ProjectionStore(Protocol):
    def load_checkpoint(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionCheckpointV1: ...

    def load_snapshot(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionSnapshotV1 | None: ...

    def apply(
        self,
        identity: ProjectionIdentityV1,
        stream_id: str,
        *,
        expected_sequence: int,
        event: HandEventV1,
        payload: dict[str, JsonValue],
    ) -> ProjectionSnapshotV1: ...

    def discard(self, identity: ProjectionIdentityV1, stream_id: str) -> None: ...


@runtime_checkable
class OutboxStore(Protocol):
    def claim_outbox(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int = 100,
    ) -> tuple[OutboxMessageV1, ...]: ...

    def load_outbox(self, message_id: str) -> OutboxMessageV1 | None: ...

    def mark_outbox_dispatched(self, *, message_id: str, worker_id: str) -> None: ...

    def retry_outbox(
        self,
        *,
        message_id: str,
        worker_id: str,
        available_at: datetime,
        error: str,
    ) -> None: ...


class OutboxDispatchResultV1(SimulatorContractV1):
    claimed_count: Annotated[StrictInt, Field(ge=0)] = 0
    dispatched_count: Annotated[StrictInt, Field(ge=0)] = 0
    failed_count: Annotated[StrictInt, Field(ge=0)] = 0


class OutboxDispatcher:
    """At-least-once dispatcher requiring idempotency-key support downstream."""

    def __init__(self, store: OutboxStore):
        self._store = store

    def dispatch_once(
        self,
        *,
        worker_id: str,
        dispatch: Callable[[OutboxMessageV1], None],
        now: datetime,
        lease_seconds: int = 30,
        retry_delay_seconds: int = 1,
        limit: int = 100,
    ) -> OutboxDispatchResultV1:
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        claimed = self._store.claim_outbox(
            worker_id=worker_id,
            now=now,
            lease_seconds=lease_seconds,
            limit=limit,
        )
        dispatched_count = 0
        failed_count = 0
        for message in claimed:
            try:
                dispatch(message)
            except Exception as exc:
                from datetime import timedelta

                detail = str(exc).strip() or type(exc).__name__
                self._store.retry_outbox(
                    message_id=message.message_id,
                    worker_id=worker_id,
                    available_at=now + timedelta(seconds=retry_delay_seconds),
                    error=detail[:512],
                )
                failed_count += 1
            else:
                self._store.mark_outbox_dispatched(
                    message_id=message.message_id,
                    worker_id=worker_id,
                )
                dispatched_count += 1
        return OutboxDispatchResultV1(
            claimed_count=len(claimed),
            dispatched_count=dispatched_count,
            failed_count=failed_count,
        )


ProjectionFunction = Callable[
    [dict[str, JsonValue] | None, HandEventV1], dict[str, JsonValue]
]


class ProjectionRunner:
    """Incrementally materialize a disposable cache from the authoritative stream."""

    def __init__(
        self,
        event_store: HandEventStore,
        projection_store: ProjectionStore,
        identity: ProjectionIdentityV1,
        projector: ProjectionFunction,
    ):
        self._event_store = event_store
        self._projection_store = projection_store
        self._identity = identity
        self._projector = projector

    def run(self, stream_id: str) -> ProjectionSnapshotV1 | None:
        checkpoint = self._projection_store.load_checkpoint(self._identity, stream_id)
        snapshot = self._projection_store.load_snapshot(self._identity, stream_id)
        if checkpoint.last_sequence and snapshot is None:
            raise ProjectionNeedsRebuild(
                "snapshot_missing",
                "checkpoint exists without its disposable snapshot; rebuild is required",
            )
        if snapshot is not None and (
            snapshot.sequence != checkpoint.last_sequence
            or snapshot.event_id != checkpoint.last_event_id
        ):
            raise ProjectionNeedsRebuild(
                "snapshot_checkpoint_mismatch",
                "snapshot and checkpoint positions disagree; rebuild is required",
            )
        for raw in self._event_store.read(stream_id):
            event = raw.event
            if event.sequence <= checkpoint.last_sequence:
                continue
            if event.sequence != checkpoint.last_sequence + 1:
                raise ProjectionSequenceError(
                    "projection_gap",
                    f"expected sequence {checkpoint.last_sequence + 1}, got {event.sequence}",
                )
            prior = (
                None
                if snapshot is None
                else json.loads(
                    json.dumps(snapshot.payload, ensure_ascii=False, allow_nan=False)
                )
            )
            payload = self._projector(prior, event)
            snapshot = self._projection_store.apply(
                self._identity,
                stream_id,
                expected_sequence=checkpoint.last_sequence,
                event=event,
                payload=payload,
            )
            checkpoint = ProjectionCheckpointV1(
                projection_identity=self._identity,
                stream_id=stream_id,
                last_sequence=event.sequence,
                last_event_id=event.event_id,
            )
        return snapshot

    def rebuild(self, stream_id: str) -> ProjectionSnapshotV1 | None:
        self._projection_store.discard(self._identity, stream_id)
        return self.run(stream_id)


__all__ = [
    "OutboxIntentV1",
    "OutboxDispatcher",
    "OutboxDispatchResultV1",
    "OutboxMessageV1",
    "OutboxStatusV1",
    "OutboxStore",
    "ProjectionCheckpointV1",
    "ProjectionError",
    "ProjectionIdentityV1",
    "ProjectionNeedsRebuild",
    "ProjectionRunner",
    "ProjectionSequenceError",
    "ProjectionSnapshotV1",
    "ProjectionStoreFailure",
    "ProjectionStore",
]
