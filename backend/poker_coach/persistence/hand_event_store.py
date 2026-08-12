"""SQLite and PostgreSQL adapters for the durable HandEventStore port."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
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
    RawHandEventV1,
    validate_append_batch,
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
        with self._lock:
            self._connection.executescript(schema)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def append(
        self,
        *,
        hand_id: str,
        expected_sequence: int,
        events: Sequence[RawHandEventV1],
    ) -> HandEventAppendResult:
        batch = validate_append_batch(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=events,
        )
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
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                message = str(exc).lower()
                if "event_id" in message:
                    raise HandEventIdentityConflict(
                        "event_id_conflict",
                        "event_id is already present in the durable event log",
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
    ) -> HandEventAppendResult:
        batch = validate_append_batch(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=events,
        )
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

    def _initialize(self) -> None:
        schema = Path(__file__).with_name("hand_events_schema.sql").read_text(
            encoding="utf-8"
        )
        try:
            with self._transaction() as cursor:
                for statement in schema.split(";\n"):
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


__all__ = ["PostgresHandEventStore", "SQLiteHandEventStore"]
