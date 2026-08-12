"""Minimal durable SQLite ownership seam for authoritative game sessions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from poker_coach.simulator.contracts import HandCompletedPayloadV1
from poker_coach.simulator.event_store import HandEventStore
from poker_coach.simulator.replay import replay_hand
from poker_coach.simulator.session import GameSession


class GameSessionStoreError(RuntimeError):
    """Stable repository failure without leaking SQLite driver details."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SessionRevisionConflict(GameSessionStoreError):
    """The durable session changed after the caller read it."""


@dataclass(frozen=True)
class StoredGameSession:
    """A validated session snapshot and its optimistic concurrency revision."""

    session: GameSession
    revision: int


class SQLiteGameSessionStore:
    """Persist session ownership and reconcile a crash after terminal append.

    Hand events remain authoritative for rule transitions.  The snapshot owns
    only cross-hand stacks, button, hand sequence, and the currently active hand.
    A terminal event batch may commit before its successor snapshot; ``recover``
    closes exactly that window by replaying the active hand from durable events.
    """

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
        schema = Path(__file__).with_name("game_session_schema.sql").read_text(
            encoding="utf-8"
        )
        with self._lock:
            self._connection.executescript(schema)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def load(self, session_id: str) -> StoredGameSession:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT schema_version, revision, session_json "
                    "FROM game_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        except sqlite3.DatabaseError:
            raise GameSessionStoreError(
                "storage_failure", "SQLite game session persistence failed"
            ) from None
        if row is None:
            raise GameSessionStoreError(
                "session_not_found", f"game session {session_id!r} is not durable"
            )
        if int(row["schema_version"]) != 1:
            raise GameSessionStoreError(
                "unsupported_session_schema_version",
                "the durable game session schema version is not supported",
            )
        return StoredGameSession(
            session=GameSession.model_validate_json(str(row["session_json"])),
            revision=int(row["revision"]),
        )

    def save(
        self, session: GameSession, *, expected_revision: int
    ) -> StoredGameSession:
        if expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        serialized = session.to_json()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT revision, session_json FROM game_sessions "
                    "WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()
                if row is None:
                    if expected_revision != 0:
                        raise SessionRevisionConflict(
                            "session_revision_conflict",
                            "new game sessions require expected revision zero",
                        )
                    revision = 1
                    self._connection.execute(
                        "INSERT INTO game_sessions "
                        "(session_id, schema_version, revision, session_json, updated_at) "
                        "VALUES (?, 1, ?, ?, ?)",
                        (
                            session.session_id,
                            revision,
                            serialized,
                            _utc_now(),
                        ),
                    )
                else:
                    current_revision = int(row["revision"])
                    if str(row["session_json"]) == serialized:
                        self._connection.commit()
                        return StoredGameSession(
                            session=session,
                            revision=current_revision,
                        )
                    if current_revision != expected_revision:
                        raise SessionRevisionConflict(
                            "session_revision_conflict",
                            f"expected revision {expected_revision}, got {current_revision}",
                        )
                    revision = current_revision + 1
                    self._connection.execute(
                        "UPDATE game_sessions SET revision = ?, session_json = ?, "
                        "updated_at = ? WHERE session_id = ?",
                        (revision, serialized, _utc_now(), session.session_id),
                    )
            except (GameSessionStoreError, ValueError):
                self._connection.rollback()
                raise
            except sqlite3.DatabaseError:
                self._connection.rollback()
                raise GameSessionStoreError(
                    "storage_failure", "SQLite game session persistence failed"
                ) from None
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return StoredGameSession(session=session, revision=revision)

    def recover(
        self, session_id: str, *, event_store: HandEventStore
    ) -> StoredGameSession:
        """Reconcile a stored active hand if its terminal event is durable."""

        stored = self.load(session_id)
        active = stored.session.active_hand
        if active is None:
            return stored
        durable = tuple(item.event for item in event_store.read(active.hand_id))
        if not durable:
            return stored
        replayed = replay_hand(durable)
        if replayed.state.hand_in_progress or not isinstance(
            durable[-1].payload, HandCompletedPayloadV1
        ):
            return stored
        successor = stored.session.complete_active_hand(
            hand_id=active.hand_id,
            ending_stacks=replayed.state.stacks,
        )
        return self.save(successor, expected_revision=stored.revision)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "GameSessionStoreError",
    "SessionRevisionConflict",
    "SQLiteGameSessionStore",
    "StoredGameSession",
]
