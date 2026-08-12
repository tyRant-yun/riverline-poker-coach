"""SQLite adapter for disposable, idempotent session statistics projections."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from poker_coach.simulator.session_stats import (
    _COUNT_FIELDS,
    _session_stats,
    SessionStatsV1,
    empty_session_stats,
)
from .projection_store import SQLiteProjectionStore
from poker_coach.simulator.recovery import UnsupportedRecoverySchemaVersion


class SQLiteSessionStatsStore:
    """Keeps a replaceable aggregate plus a durable per-session hand checkpoint."""

    def __init__(self, path: str | Path):
        self._lock = RLock()
        self._connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self.hand_projection_store = SQLiteProjectionStore(path)
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS session_stats_snapshots (
                session_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL, fingerprint TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_stats_applied_hands (
                session_id TEXT NOT NULL, hand_id TEXT NOT NULL,
                PRIMARY KEY (session_id, hand_id)
            );
            """
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
        self.hand_projection_store.close()

    def load(self, session_id: str) -> SessionStatsV1:
        with self._lock:
            row = self._connection.execute("SELECT schema_version, payload_json FROM session_stats_snapshots WHERE session_id = ?", (session_id,)).fetchone()
        if row is not None and int(row["schema_version"]) != 1:
            raise UnsupportedRecoverySchemaVersion(
                resource="session_stats_snapshot", schema_version=int(row["schema_version"])
            )
        return empty_session_stats(session_id) if row is None else SessionStatsV1.model_validate_json(row["payload_json"])

    def apply_hand(self, session_id: str, hand_id: str, contribution: SessionStatsV1) -> SessionStatsV1:
        if contribution.session_id != session_id:
            raise ValueError("contribution must match session_id")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute("SELECT schema_version, payload_json FROM session_stats_snapshots WHERE session_id = ?", (session_id,)).fetchone()
                if row is not None and int(row["schema_version"]) != 1:
                    raise UnsupportedRecoverySchemaVersion(
                        resource="session_stats_snapshot", schema_version=int(row["schema_version"])
                    )
                current = empty_session_stats(session_id) if row is None else SessionStatsV1.model_validate_json(row["payload_json"])
                applied = self._connection.execute("SELECT 1 FROM session_stats_applied_hands WHERE session_id = ? AND hand_id = ?", (session_id, hand_id)).fetchone()
                if applied is not None:
                    self._connection.execute("COMMIT")
                    return current
                merged: dict[int, dict[str, int]] = {}
                for seat in set(current.by_seat) | set(contribution.by_seat):
                    before = current.by_seat.get(seat)
                    delta = contribution.by_seat.get(seat)
                    merged[seat] = {field: (getattr(before, field) if before else 0) + (getattr(delta, field) if delta else 0) for field in _COUNT_FIELDS}
                result = _session_stats(session_id, merged)
                self._connection.execute("INSERT INTO session_stats_applied_hands (session_id, hand_id) VALUES (?, ?)", (session_id, hand_id))
                self._connection.execute(
                    "INSERT INTO session_stats_snapshots (session_id, schema_version, payload_json, fingerprint) VALUES (?, 1, ?, ?) ON CONFLICT(session_id) DO UPDATE SET schema_version = 1, payload_json = excluded.payload_json, fingerprint = excluded.fingerprint",
                    (session_id, result.to_json(), result.fingerprint),
                )
                self._connection.execute("COMMIT")
                return result
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def discard(self, session_id: str) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute("DELETE FROM session_stats_applied_hands WHERE session_id = ?", (session_id,))
                self._connection.execute("DELETE FROM session_stats_snapshots WHERE session_id = ?", (session_id,))
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
