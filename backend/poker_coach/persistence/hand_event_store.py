"""SQLite and PostgreSQL adapters for the durable HandEventStore port."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Sequence

from poker_coach.simulator.event_store import (
    ExpectedSequenceConflict,
    HandEventAppendResult,
    HandEventAppendRetryable,
    HandEventIdentityConflict,
    HandEventStoreError,
    HandEventStoreFailure,
    OutboxIdentityConflict,
    OutboxBindingError,
    RawHandEventV1,
    validate_append_batch,
)
from poker_coach.simulator.recovery import (
    OutboxIntentV1,
    OutboxClaimError,
    OutboxMessageV1,
    OutboxStatusV1,
    UnsupportedRecoverySchemaVersion,
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SQLiteHandEventStore:
    """SQLite adapter using ``BEGIN IMMEDIATE`` to serialize hand appends."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
            timeout=timeout_seconds,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
        schema = Path(__file__).with_name("hand_events_schema.sql").read_text(
            encoding="utf-8"
        )
        outbox_schema = Path(__file__).with_name("outbox_schema.sql").read_text(
            encoding="utf-8"
        )
        with self._lock:
            self._connection.executescript(schema)
            self._connection.executescript(outbox_schema)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def append(
        self,
        *,
        hand_id: str,
        expected_sequence: int,
        events: Sequence[RawHandEventV1],
        outbox_intents: Sequence[OutboxIntentV1] = (),
    ) -> HandEventAppendResult:
        batch = validate_append_batch(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=events,
        )
        intents = _validate_outbox_intents(outbox_intents, events=batch)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                    "FROM hand_events WHERE hand_id = ?",
                    (hand_id,),
                ).fetchone()
                actual_sequence = int(row["sequence"])
                if actual_sequence != expected_sequence:
                    raise ExpectedSequenceConflict(
                        hand_id=hand_id,
                        expected_sequence=expected_sequence,
                        actual_sequence=actual_sequence,
                    )
                self._connection.executemany(
                    """
                    INSERT INTO hand_events
                        (event_id, hand_id, sequence, schema_version, source,
                         provenance_json, payload_json, raw_event_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.event.event_id,
                            item.event.hand_id,
                            item.event.sequence,
                            item.event.schema_version,
                            item.event.source.value,
                            _json(item.event.provenance.to_dict()),
                            _json(item.event.payload.to_dict()),
                            item.raw_json,
                        )
                        for item in batch
                    ],
                )
                self._connection.executemany(
                    """
                    INSERT INTO outbox_messages
                        (message_id, source_event_id, idempotency_key, schema_version, topic,
                         payload_json, status, attempt_count, available_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0,
                            '1970-01-01T00:00:00+00:00')
                    """,
                    [
                        (
                            intent.message_id,
                            intent.source_event_id,
                            intent.idempotency_key,
                            intent.schema_version,
                            intent.topic,
                            _json(intent.payload),
                        )
                        for intent in intents
                    ],
                )
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                message = str(exc).lower()
                if "event_id" in message:
                    raise HandEventIdentityConflict(
                        "event_id_conflict",
                        "event_id is already present in the durable event log",
                    ) from None
                if "outbox" in message or "idempotency_key" in message:
                    raise OutboxIdentityConflict(
                        "outbox_identity_conflict",
                        "outbox message_id or idempotency_key is already durable",
                    ) from None
                raise HandEventIdentityConflict(
                    "sequence_conflict",
                    "hand sequence is already present in the durable event log",
                ) from None
            except sqlite3.OperationalError as exc:
                self._connection.rollback()
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise HandEventAppendRetryable(
                        "append_retryable",
                        "the complete append transaction may be retried by the caller",
                    ) from None
                raise HandEventStoreFailure(
                    "storage_failure", "SQLite hand event persistence failed"
                ) from None
            except sqlite3.DatabaseError:
                self._connection.rollback()
                raise HandEventStoreFailure(
                    "storage_failure", "SQLite hand event persistence failed"
                ) from None
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return HandEventAppendResult(
            hand_id=hand_id,
            previous_sequence=expected_sequence,
            appended_count=len(batch),
            last_sequence=batch[-1].event.sequence,
        )

    def read(self, hand_id: str) -> tuple[RawHandEventV1, ...]:
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT raw_event_json FROM hand_events "
                    "WHERE hand_id = ? ORDER BY sequence ASC",
                    (hand_id,),
                ).fetchall()
        except sqlite3.DatabaseError:
            raise HandEventStoreFailure(
                "storage_failure", "SQLite hand event persistence failed"
            ) from None
        return tuple(RawHandEventV1.from_json(row["raw_event_json"]) for row in rows)

    def claim_outbox(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int = 100,
    ) -> tuple[OutboxMessageV1, ...]:
        if not worker_id or lease_seconds <= 0 or limit <= 0:
            raise ValueError("worker_id, lease_seconds and limit must be positive")
        now_text = _utc_iso(now)
        lease_text = _utc_iso(now + timedelta(seconds=lease_seconds))
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "UPDATE outbox_messages SET status = 'pending', claimed_by = NULL, "
                    "lease_expires_at = NULL, claim_token = NULL "
                    "WHERE status = 'processing' "
                    "AND lease_expires_at <= ?",
                    (now_text,),
                )
                rows = self._connection.execute(
                    "SELECT message_id FROM outbox_messages "
                    "WHERE status = 'pending' AND available_at <= ? "
                    "ORDER BY message_id LIMIT ?",
                    (now_text, limit),
                ).fetchall()
                message_ids = [str(row["message_id"]) for row in rows]
                for message_id in message_ids:
                    claim_token = uuid.uuid4().hex
                    self._connection.execute(
                        "UPDATE outbox_messages SET status = 'processing', "
                        "attempt_count = attempt_count + 1, claimed_by = ?, "
                        "lease_expires_at = ?, claim_token = ? "
                        "WHERE message_id = ? AND status = 'pending'",
                        (worker_id, lease_text, claim_token, message_id),
                    )
                claimed = [
                    self._connection.execute(
                        "SELECT * FROM outbox_messages WHERE message_id = ?",
                        (message_id,),
                    ).fetchone()
                    for message_id in message_ids
                ]
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return tuple(_outbox_message_from_row(row) for row in claimed)

    def load_outbox(self, message_id: str) -> OutboxMessageV1 | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM outbox_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return None if row is None else _outbox_message_from_row(row)

    def mark_outbox_dispatched(
        self,
        *,
        message_id: str,
        worker_id: str,
        claim_token: str,
        now: datetime,
    ) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    "UPDATE outbox_messages SET status = 'dispatched', "
                    "claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL, "
                    "last_error = NULL WHERE message_id = ? AND status = 'processing' "
                    "AND claimed_by = ? AND claim_token = ? AND lease_expires_at > ?",
                    (message_id, worker_id, claim_token, _utc_iso(now)),
                )
                if cursor.rowcount != 1:
                    raise OutboxClaimError(
                        "outbox_claim_lost",
                        "outbox claim is no longer owned by this worker and token",
                    )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def retry_outbox(
        self,
        *,
        message_id: str,
        worker_id: str,
        claim_token: str,
        now: datetime,
        available_at: datetime,
        error: str,
    ) -> None:
        if not error:
            raise ValueError("outbox retry requires an error")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    "UPDATE outbox_messages SET status = 'pending', available_at = ?, "
                    "claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL, "
                    "last_error = ? WHERE message_id = ? AND status = 'processing' "
                    "AND claimed_by = ? AND claim_token = ? AND lease_expires_at > ?",
                    (
                        _utc_iso(available_at),
                        error[:512],
                        message_id,
                        worker_id,
                        claim_token,
                        _utc_iso(now),
                    ),
                )
                if cursor.rowcount != 1:
                    raise OutboxClaimError(
                        "outbox_claim_lost",
                        "outbox claim is no longer owned by this worker and token",
                    )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()


class PostgresHandEventStore:
    """PostgreSQL adapter using a per-hand transaction advisory lock.

    Under PostgreSQL's default READ COMMITTED isolation, the advisory lock
    serializes the head read and inserts for one hand. Unique constraints remain
    the final authority for global event IDs and per-hand sequences.
    """

    def __init__(self, dsn: str, *, connection=None):
        self.dsn = dsn
        self._owns_connection = connection is None
        if connection is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - deployment only
                raise HandEventStoreFailure(
                    "postgres_unavailable",
                    "PostgreSQL hand event persistence requires psycopg",
                ) from None
            connection = psycopg.connect(dsn)
        self._connection = connection
        self._initialize()

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def append(
        self,
        *,
        hand_id: str,
        expected_sequence: int,
        events: Sequence[RawHandEventV1],
        outbox_intents: Sequence[OutboxIntentV1] = (),
    ) -> HandEventAppendResult:
        batch = validate_append_batch(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=events,
        )
        intents = _validate_outbox_intents(outbox_intents, events=batch)
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (hand_id,),
                )
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                    "FROM hand_events WHERE hand_id = %s",
                    (hand_id,),
                )
                actual_sequence = int(_first_value(cursor.fetchone(), "sequence"))
                if actual_sequence != expected_sequence:
                    raise ExpectedSequenceConflict(
                        hand_id=hand_id,
                        expected_sequence=expected_sequence,
                        actual_sequence=actual_sequence,
                    )
                for item in batch:
                    cursor.execute(
                        """
                        INSERT INTO hand_events
                            (event_id, hand_id, sequence, schema_version, source,
                             provenance_json, payload_json, raw_event_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            item.event.event_id,
                            item.event.hand_id,
                            item.event.sequence,
                            item.event.schema_version,
                            item.event.source.value,
                            _json(item.event.provenance.to_dict()),
                            _json(item.event.payload.to_dict()),
                            item.raw_json,
                        ),
                    )
                for intent in intents:
                    cursor.execute(
                        """
                        INSERT INTO outbox_messages
                            (message_id, source_event_id, idempotency_key, schema_version, topic,
                             payload_json, status, attempt_count, available_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'pending', 0,
                                '1970-01-01T00:00:00+00:00')
                        """,
                        (
                            intent.message_id,
                            intent.source_event_id,
                            intent.idempotency_key,
                            intent.schema_version,
                            intent.topic,
                            _json(intent.payload),
                        ),
                    )
        except HandEventStoreError:
            raise
        except Exception as exc:
            raise _postgres_domain_error(exc) from None
        return HandEventAppendResult(
            hand_id=hand_id,
            previous_sequence=expected_sequence,
            appended_count=len(batch),
            last_sequence=batch[-1].event.sequence,
        )

    def read(self, hand_id: str) -> tuple[RawHandEventV1, ...]:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT raw_event_json FROM hand_events "
                    "WHERE hand_id = %s ORDER BY sequence ASC",
                    (hand_id,),
                )
                rows = cursor.fetchall()
        except Exception as exc:
            raise _postgres_domain_error(exc) from None
        return tuple(
            RawHandEventV1.from_json(str(_first_value(row, "raw_event_json")))
            for row in rows
        )

    def claim_outbox(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int = 100,
    ) -> tuple[OutboxMessageV1, ...]:
        if not worker_id or lease_seconds <= 0 or limit <= 0:
            raise ValueError("worker_id, lease_seconds and limit must be positive")
        now_text = _utc_iso(now)
        lease_text = _utc_iso(now + timedelta(seconds=lease_seconds))
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "UPDATE outbox_messages SET status = 'pending', claimed_by = NULL, "
                    "lease_expires_at = NULL, claim_token = NULL "
                    "WHERE status = 'processing' "
                    "AND lease_expires_at <= %s",
                    (now_text,),
                )
                cursor.execute(
                    "SELECT message_id FROM outbox_messages "
                    "WHERE status = 'pending' AND available_at <= %s "
                    "ORDER BY message_id LIMIT %s FOR UPDATE SKIP LOCKED",
                    (now_text, limit),
                )
                message_ids = [
                    str(_first_value(row, "message_id")) for row in cursor.fetchall()
                ]
                claimed = []
                for message_id in message_ids:
                    claim_token = uuid.uuid4().hex
                    cursor.execute(
                        "UPDATE outbox_messages SET status = 'processing', "
                        "attempt_count = attempt_count + 1, claimed_by = %s, "
                        "lease_expires_at = %s, claim_token = %s WHERE message_id = %s "
                        "RETURNING message_id, source_event_id, idempotency_key, schema_version, topic, "
                        "payload_json, status, attempt_count, available_at, claimed_by, "
                        "lease_expires_at, claim_token, last_error",
                        (worker_id, lease_text, claim_token, message_id),
                    )
                    claimed.append(cursor.fetchone())
        except UnsupportedRecoverySchemaVersion:
            raise
        except Exception as exc:
            raise _postgres_domain_error(exc) from None
        return tuple(_outbox_message_from_row(row) for row in claimed)

    def load_outbox(self, message_id: str) -> OutboxMessageV1 | None:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT message_id, source_event_id, idempotency_key, schema_version, topic, "
                    "payload_json, status, attempt_count, available_at, claimed_by, "
                    "lease_expires_at, claim_token, last_error FROM outbox_messages "
                    "WHERE message_id = %s",
                    (message_id,),
                )
                row = cursor.fetchone()
        except Exception as exc:
            raise _postgres_domain_error(exc) from None
        return None if row is None else _outbox_message_from_row(row)

    def mark_outbox_dispatched(
        self,
        *,
        message_id: str,
        worker_id: str,
        claim_token: str,
        now: datetime,
    ) -> None:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "UPDATE outbox_messages SET status = 'dispatched', "
                    "claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL, "
                    "last_error = NULL WHERE message_id = %s AND status = 'processing' "
                    "AND claimed_by = %s AND claim_token = %s AND lease_expires_at > %s",
                    (message_id, worker_id, claim_token, _utc_iso(now)),
                )
                if cursor.rowcount != 1:
                    raise OutboxClaimError(
                        "outbox_claim_lost",
                        "outbox claim is no longer owned by this worker and token",
                    )
        except (HandEventStoreError, OutboxClaimError):
            raise
        except Exception as exc:
            raise _postgres_domain_error(exc) from None

    def retry_outbox(
        self,
        *,
        message_id: str,
        worker_id: str,
        claim_token: str,
        now: datetime,
        available_at: datetime,
        error: str,
    ) -> None:
        if not error:
            raise ValueError("outbox retry requires an error")
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "UPDATE outbox_messages SET status = 'pending', available_at = %s, "
                    "claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL, "
                    "last_error = %s WHERE message_id = %s AND status = 'processing' "
                    "AND claimed_by = %s AND claim_token = %s AND lease_expires_at > %s",
                    (
                        _utc_iso(available_at),
                        error[:512],
                        message_id,
                        worker_id,
                        claim_token,
                        _utc_iso(now),
                    ),
                )
                if cursor.rowcount != 1:
                    raise OutboxClaimError(
                        "outbox_claim_lost",
                        "outbox claim is no longer owned by this worker and token",
                    )
        except (HandEventStoreError, OutboxClaimError):
            raise
        except Exception as exc:
            raise _postgres_domain_error(exc) from None

    def _initialize(self) -> None:
        schemas = (
            Path(__file__).with_name("hand_events_schema.sql"),
            Path(__file__).with_name("outbox_schema.sql"),
        )
        try:
            with self._transaction() as cursor:
                for path in schemas:
                    for statement in path.read_text(encoding="utf-8").split(";\n"):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
        except HandEventStoreError:
            raise
        except Exception as exc:
            raise _postgres_domain_error(exc) from None

    @contextmanager
    def _transaction(self):
        cursor = self._connection.cursor()
        try:
            yield cursor
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        finally:
            cursor.close()


def _first_value(row, name: str):
    if isinstance(row, dict):
        return row[name]
    return row[0]


def _postgres_domain_error(exc: Exception) -> HandEventStoreError:
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    diagnostic = getattr(exc, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", "") or ""
    if sqlstate == "23505":
        if constraint == "pk_hand_events":
            return HandEventIdentityConflict(
                "event_id_conflict",
                "event_id is already present in the durable event log",
            )
        if constraint in {"pk_outbox_messages", "uq_outbox_messages_idempotency_key"}:
            return OutboxIdentityConflict(
                "outbox_identity_conflict",
                "outbox message_id or idempotency_key is already durable",
            )
        return HandEventIdentityConflict(
            "sequence_conflict",
            "hand sequence is already present in the durable event log",
        )
    if sqlstate in {"40001", "40P01", "55P03"}:
        return HandEventAppendRetryable(
            "append_retryable",
            "the complete append transaction may be retried by the caller",
        )
    return HandEventStoreFailure(
        "storage_failure", "PostgreSQL hand event persistence failed"
    )


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("outbox timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _outbox_message_from_row(row) -> OutboxMessageV1:
    def value(name: str, index: int):
        try:
            return row[name]
        except (TypeError, IndexError):
            return row[index]

    schema_version = int(value("schema_version", 3))
    if schema_version != 1:
        raise UnsupportedRecoverySchemaVersion(
            resource="outbox_message", schema_version=schema_version
        )
    return OutboxMessageV1(
        message_id=str(value("message_id", 0)),
        source_event_id=str(value("source_event_id", 1)),
        idempotency_key=str(value("idempotency_key", 2)),
        topic=str(value("topic", 4)),
        payload=json.loads(str(value("payload_json", 5))),
        status=OutboxStatusV1(str(value("status", 6))),
        attempt_count=int(value("attempt_count", 7)),
        available_at=datetime.fromisoformat(str(value("available_at", 8))),
        claimed_by=(
            None if value("claimed_by", 9) is None else str(value("claimed_by", 9))
        ),
        lease_expires_at=(
            None
            if value("lease_expires_at", 10) is None
            else datetime.fromisoformat(str(value("lease_expires_at", 10)))
        ),
        claim_token=(
            None if value("claim_token", 11) is None else str(value("claim_token", 11))
        ),
        last_error=(
            None if value("last_error", 12) is None else str(value("last_error", 12))
        ),
    )


def _validate_outbox_intents(
    intents: Sequence[OutboxIntentV1],
    *,
    events: Sequence[RawHandEventV1],
) -> tuple[OutboxIntentV1, ...]:
    batch = tuple(intents)
    message_ids = [intent.message_id for intent in batch]
    keys = [intent.idempotency_key for intent in batch]
    if len(message_ids) != len(set(message_ids)) or len(keys) != len(set(keys)):
        raise OutboxIdentityConflict(
            "duplicate_outbox_identity_in_batch",
            "outbox message_id and idempotency_key values must be unique within a batch",
        )
    batch_event_ids = {item.event.event_id for item in events}
    if any(intent.source_event_id not in batch_event_ids for intent in batch):
        raise OutboxBindingError(
            "outbox_source_not_in_batch",
            "every outbox source_event_id must reference an event in the same append batch",
        )
    return batch


__all__ = ["PostgresHandEventStore", "SQLiteHandEventStore"]
