"""SQLite persistence for disposable automatic-review read models."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from poker_coach.simulator.auto_review import AutomaticReviewV1
from poker_coach.simulator.recovery import UnsupportedRecoverySchemaVersion

from .projection_store import SQLiteProjectionStore


class SQLiteReviewProjectionStore:
    """A unique `(session, hand, hero)` record makes delivery/restart idempotent."""

    def __init__(self, path: str | Path):
        self._lock = RLock()
        self._connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self.hand_projection_store = SQLiteProjectionStore(path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS automatic_reviews (
                session_id TEXT NOT NULL, hand_id TEXT NOT NULL, hero_seat INTEGER NOT NULL,
                schema_version INTEGER NOT NULL, payload_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY (session_id, hand_id, hero_seat)
            )"""
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
        self.hand_projection_store.close()

    def apply(self, review: AutomaticReviewV1) -> AutomaticReviewV1:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT schema_version, payload_json FROM automatic_reviews WHERE session_id = ? AND hand_id = ? AND hero_seat = ?",
                    (review.session_id, review.hand_id, review.hero_seat),
                ).fetchone()
                if row is not None:
                    if int(row["schema_version"]) != 1:
                        raise UnsupportedRecoverySchemaVersion(resource="automatic_review", schema_version=int(row["schema_version"]))
                    self._connection.execute("COMMIT")
                    return AutomaticReviewV1.model_validate_json(row["payload_json"])
                self._connection.execute(
                    "INSERT INTO automatic_reviews (session_id, hand_id, hero_seat, schema_version, payload_json, fingerprint) VALUES (?, ?, ?, 1, ?, ?)",
                    (review.session_id, review.hand_id, review.hero_seat, review.to_json(), review.fingerprint),
                )
                self._connection.execute("COMMIT")
                return review
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def count(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM automatic_reviews").fetchone()[0])
