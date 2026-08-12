"""SQLite projection checkpoint and disposable snapshot adapter."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from pydantic import JsonValue

from poker_coach.simulator.contracts import HandEventV1
from poker_coach.simulator.recovery import (
    ProjectionCheckpointV1,
    ProjectionIdentityV1,
    ProjectionSequenceError,
    ProjectionSnapshotV1,
    ProjectionStoreFailure,
    UnsupportedRecoverySchemaVersion,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SQLiteProjectionStore:
    """Atomically writes a read-model snapshot before advancing its checkpoint."""

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
        self._connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
        schema = Path(__file__).with_name("projection_schema.sql").read_text(
            encoding="utf-8"
        )
        with self._lock:
            self._connection.executescript(schema)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def load_checkpoint(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionCheckpointV1:
        with self._lock:
            row = self._connection.execute(
                "SELECT last_sequence, last_event_id FROM projection_checkpoints "
                "WHERE projection_name = ? AND projection_version = ? AND stream_id = ?",
                (identity.projection_name, identity.projection_version, stream_id),
            ).fetchone()
        if row is None:
            return ProjectionCheckpointV1(
                projection_identity=identity,
                stream_id=stream_id,
            )
        return ProjectionCheckpointV1(
            projection_identity=identity,
            stream_id=stream_id,
            last_sequence=int(row["last_sequence"]),
            last_event_id=str(row["last_event_id"]),
        )

    def load_snapshot(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionSnapshotV1 | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT sequence, event_id, schema_version, payload_json, fingerprint "
                "FROM projection_snapshots WHERE projection_name = ? "
                "AND projection_version = ? AND stream_id = ?",
                (identity.projection_name, identity.projection_version, stream_id),
            ).fetchone()
        if row is None:
            return None
        _require_v1_schema("projection_snapshot", int(row["schema_version"]))
        return ProjectionSnapshotV1(
            projection_identity=identity,
            stream_id=stream_id,
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            payload=json.loads(str(row["payload_json"])),
            fingerprint=str(row["fingerprint"]),
        )

    def apply(
        self,
        identity: ProjectionIdentityV1,
        stream_id: str,
        *,
        expected_sequence: int,
        event: HandEventV1,
        payload: dict[str, JsonValue],
    ) -> ProjectionSnapshotV1:
        if event.hand_id != stream_id:
            raise ProjectionSequenceError(
                "mixed_stream", "projection event must match stream_id"
            )
        payload_json = _canonical_json(payload)
        fingerprint = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT last_sequence FROM projection_checkpoints "
                    "WHERE projection_name = ? AND projection_version = ? "
                    "AND stream_id = ?",
                    (identity.projection_name, identity.projection_version, stream_id),
                ).fetchone()
                actual_sequence = 0 if row is None else int(row["last_sequence"])
                if actual_sequence != expected_sequence:
                    raise ProjectionSequenceError(
                        "checkpoint_conflict",
                        f"checkpoint is {actual_sequence}, not expected {expected_sequence}",
                    )
                if event.sequence != expected_sequence + 1:
                    raise ProjectionSequenceError(
                        "projection_gap",
                        f"event sequence must be {expected_sequence + 1}",
                    )
                self._connection.execute(
                    """
                    INSERT INTO projection_snapshots
                        (projection_name, projection_version, stream_id, sequence,
                         event_id, schema_version, payload_json, fingerprint)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT (projection_name, projection_version, stream_id)
                    DO UPDATE SET sequence = excluded.sequence,
                                  event_id = excluded.event_id,
                                  schema_version = excluded.schema_version,
                                  payload_json = excluded.payload_json,
                                  fingerprint = excluded.fingerprint
                    """,
                    (
                        identity.projection_name,
                        identity.projection_version,
                        stream_id,
                        event.sequence,
                        event.event_id,
                        payload_json,
                        fingerprint,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO projection_checkpoints
                        (projection_name, projection_version, stream_id,
                         last_sequence, last_event_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (projection_name, projection_version, stream_id)
                    DO UPDATE SET last_sequence = excluded.last_sequence,
                                  last_event_id = excluded.last_event_id
                    """,
                    (
                        identity.projection_name,
                        identity.projection_version,
                        stream_id,
                        event.sequence,
                        event.event_id,
                    ),
                )
            except ProjectionSequenceError:
                self._connection.rollback()
                raise
            except sqlite3.DatabaseError:
                self._connection.rollback()
                raise ProjectionStoreFailure(
                    "storage_failure", "SQLite projection apply failed"
                ) from None
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return ProjectionSnapshotV1(
            projection_identity=identity,
            stream_id=stream_id,
            sequence=event.sequence,
            event_id=event.event_id,
            payload=json.loads(payload_json),
            fingerprint=fingerprint,
        )

    def discard(self, identity: ProjectionIdentityV1, stream_id: str) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                key = (identity.projection_name, identity.projection_version, stream_id)
                self._connection.execute(
                    "DELETE FROM projection_snapshots WHERE projection_name = ? "
                    "AND projection_version = ? AND stream_id = ?",
                    key,
                )
                self._connection.execute(
                    "DELETE FROM projection_checkpoints WHERE projection_name = ? "
                    "AND projection_version = ? AND stream_id = ?",
                    key,
                )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()


class PostgresProjectionStore:
    """PostgreSQL adapter with snapshot and checkpoint in one transaction."""

    def __init__(self, dsn: str, *, connection=None):
        self.dsn = dsn
        self._owns_connection = connection is None
        if connection is None:
            try:
                import psycopg
            except ImportError:
                raise ProjectionStoreFailure(
                    "postgres_unavailable",
                    "PostgreSQL projection persistence requires psycopg",
                ) from None
            connection = psycopg.connect(dsn)
        self._connection = connection
        schema = Path(__file__).with_name("projection_schema.sql").read_text(
            encoding="utf-8"
        )
        try:
            with self._transaction() as cursor:
                for statement in schema.split(";\n"):
                    statement = statement.strip()
                    if statement:
                        cursor.execute(statement)
        except Exception as exc:
            raise ProjectionStoreFailure(
                "storage_failure", "PostgreSQL projection initialization failed"
            ) from exc

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def load_checkpoint(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionCheckpointV1:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT last_sequence, last_event_id FROM projection_checkpoints "
                    "WHERE projection_name = %s AND projection_version = %s "
                    "AND stream_id = %s",
                    (identity.projection_name, identity.projection_version, stream_id),
                )
                row = cursor.fetchone()
        except Exception as exc:
            raise ProjectionStoreFailure(
                "storage_failure", "PostgreSQL checkpoint read failed"
            ) from exc
        if row is None:
            return ProjectionCheckpointV1(
                projection_identity=identity,
                stream_id=stream_id,
            )
        return ProjectionCheckpointV1(
            projection_identity=identity,
            stream_id=stream_id,
            last_sequence=int(_value(row, "last_sequence", 0)),
            last_event_id=str(_value(row, "last_event_id", 1)),
        )

    def load_snapshot(
        self, identity: ProjectionIdentityV1, stream_id: str
    ) -> ProjectionSnapshotV1 | None:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT sequence, event_id, schema_version, payload_json, fingerprint "
                    "FROM projection_snapshots WHERE projection_name = %s "
                    "AND projection_version = %s AND stream_id = %s",
                    (identity.projection_name, identity.projection_version, stream_id),
                )
                row = cursor.fetchone()
        except Exception as exc:
            raise ProjectionStoreFailure(
                "storage_failure", "PostgreSQL snapshot read failed"
            ) from exc
        if row is None:
            return None
        _require_v1_schema(
            "projection_snapshot", int(_value(row, "schema_version", 2))
        )
        return ProjectionSnapshotV1(
            projection_identity=identity,
            stream_id=stream_id,
            sequence=int(_value(row, "sequence", 0)),
            event_id=str(_value(row, "event_id", 1)),
            payload=json.loads(str(_value(row, "payload_json", 3))),
            fingerprint=str(_value(row, "fingerprint", 4)),
        )

    def apply(
        self,
        identity: ProjectionIdentityV1,
        stream_id: str,
        *,
        expected_sequence: int,
        event: HandEventV1,
        payload: dict[str, JsonValue],
    ) -> ProjectionSnapshotV1:
        if event.hand_id != stream_id:
            raise ProjectionSequenceError(
                "mixed_stream", "projection event must match stream_id"
            )
        payload_json = _canonical_json(payload)
        fingerprint = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (_projection_lock_key(identity, stream_id),),
                )
                cursor.execute(
                    "SELECT last_sequence FROM projection_checkpoints "
                    "WHERE projection_name = %s AND projection_version = %s "
                    "AND stream_id = %s FOR UPDATE",
                    (identity.projection_name, identity.projection_version, stream_id),
                )
                row = cursor.fetchone()
                actual_sequence = 0 if row is None else int(_value(row, "last_sequence", 0))
                if actual_sequence != expected_sequence:
                    raise ProjectionSequenceError(
                        "checkpoint_conflict",
                        f"checkpoint is {actual_sequence}, not expected {expected_sequence}",
                    )
                if event.sequence != expected_sequence + 1:
                    raise ProjectionSequenceError(
                        "projection_gap", f"event sequence must be {expected_sequence + 1}"
                    )
                cursor.execute(
                    """
                    INSERT INTO projection_snapshots
                        (projection_name, projection_version, stream_id, sequence,
                         event_id, schema_version, payload_json, fingerprint)
                    VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
                    ON CONFLICT (projection_name, projection_version, stream_id)
                    DO UPDATE SET sequence = EXCLUDED.sequence,
                                  event_id = EXCLUDED.event_id,
                                  schema_version = EXCLUDED.schema_version,
                                  payload_json = EXCLUDED.payload_json,
                                  fingerprint = EXCLUDED.fingerprint
                    """,
                    (
                        identity.projection_name,
                        identity.projection_version,
                        stream_id,
                        event.sequence,
                        event.event_id,
                        payload_json,
                        fingerprint,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO projection_checkpoints
                        (projection_name, projection_version, stream_id,
                         last_sequence, last_event_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (projection_name, projection_version, stream_id)
                    DO UPDATE SET last_sequence = EXCLUDED.last_sequence,
                                  last_event_id = EXCLUDED.last_event_id
                    """,
                    (
                        identity.projection_name,
                        identity.projection_version,
                        stream_id,
                        event.sequence,
                        event.event_id,
                    ),
                )
        except ProjectionSequenceError:
            raise
        except Exception as exc:
            raise ProjectionStoreFailure(
                "storage_failure", "PostgreSQL projection apply failed"
            ) from exc
        return ProjectionSnapshotV1(
            projection_identity=identity,
            stream_id=stream_id,
            sequence=event.sequence,
            event_id=event.event_id,
            payload=json.loads(payload_json),
            fingerprint=fingerprint,
        )

    def discard(self, identity: ProjectionIdentityV1, stream_id: str) -> None:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (_projection_lock_key(identity, stream_id),),
                )
                key = (identity.projection_name, identity.projection_version, stream_id)
                cursor.execute(
                    "DELETE FROM projection_snapshots WHERE projection_name = %s "
                    "AND projection_version = %s AND stream_id = %s",
                    key,
                )
                cursor.execute(
                    "DELETE FROM projection_checkpoints WHERE projection_name = %s "
                    "AND projection_version = %s AND stream_id = %s",
                    key,
                )
        except Exception as exc:
            raise ProjectionStoreFailure(
                "storage_failure", "PostgreSQL projection discard failed"
            ) from exc

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


def _value(row, name: str, index: int):
    if isinstance(row, dict):
        return row[name]
    return row[index]


def _projection_lock_key(identity: ProjectionIdentityV1, stream_id: str) -> str:
    return _canonical_json(
        {
            "projectionName": identity.projection_name,
            "projectionVersion": identity.projection_version,
            "streamId": stream_id,
        }
    )


def _require_v1_schema(resource: str, schema_version: int) -> None:
    if schema_version != 1:
        raise UnsupportedRecoverySchemaVersion(
            resource=resource, schema_version=schema_version
        )


__all__ = ["PostgresProjectionStore", "SQLiteProjectionStore"]
