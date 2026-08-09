"""Recoverable local persistence for scenarios, revisions, and analysis runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from poker_coach.analysis.models import AnalysisResult
from poker_coach.domain.models import ScenarioSpec


class StoreNotFound(KeyError):
    pass


class SQLiteStore:
    """A small repository with PostgreSQL-shaped logical tables.

    SQLite is the deliberate local-default dialect. The schema uses ordinary
    relational columns and JSON snapshots so a PostgreSQL adapter can be
    introduced later without changing ScenarioSpec or API contracts.
    """

    def __init__(self, path: str | Path = ".data/poker_coach.sqlite3"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_scenario(
        self,
        scenario: ScenarioSpec,
        *,
        title: str = "Untitled scenario",
        tags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        scenario_id = uuid4().hex
        now = _now()
        serialized = scenario.to_json()
        scenario_hash = _hash(serialized)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO scenarios
                    (scenario_id, title, scenario_json, scenario_hash, tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scenario_id, title, serialized, scenario_hash, json.dumps(sorted(tags)), now, now),
            )
            self._insert_revision(connection, scenario_id, scenario, 1, now)
        return self.get_scenario(scenario_id)

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT s.*,
                       COALESCE((SELECT MAX(r.revision_no)
                                 FROM scenario_revisions r
                                 WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
                FROM scenarios s WHERE s.scenario_id = ?
                """,
                (scenario_id,),
            ).fetchone()
        if row is None:
            raise StoreNotFound(scenario_id)
        return _scenario_record(row)

    def list_scenarios(self, *, query: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._lock:
            if query:
                rows = self._connection.execute(
                    """
                    SELECT s.*,
                           COALESCE((SELECT MAX(r.revision_no)
                                     FROM scenario_revisions r
                                     WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
                    FROM scenarios s
                    WHERE title LIKE ? OR scenario_json LIKE ? OR tags_json LIKE ?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (f"%{query}%", f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT s.*,
                           COALESCE((SELECT MAX(r.revision_no)
                                     FROM scenario_revisions r
                                     WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
                    FROM scenarios s ORDER BY updated_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_scenario_record(row) for row in rows]

    def update_scenario(
        self,
        scenario_id: str,
        scenario: ScenarioSpec,
        *,
        title: str | None = None,
        tags: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        now = _now()
        serialized = scenario.to_json()
        scenario_hash = _hash(serialized)
        next_revision = int(current["revisionNo"]) + 1
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE scenarios
                SET title = ?, scenario_json = ?, scenario_hash = ?, tags_json = ?, updated_at = ?
                WHERE scenario_id = ?
                """,
                (
                    title if title is not None else current["title"],
                    serialized,
                    scenario_hash,
                    json.dumps(sorted(tags if tags is not None else current["tags"])),
                    now,
                    scenario_id,
                ),
            )
            self._insert_revision(connection, scenario_id, scenario, next_revision, now)
        return self.get_scenario(scenario_id)

    def copy_scenario(self, scenario_id: str, *, title: str | None = None) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        return self.create_scenario(
            current["scenario"],
            title=title or f"Copy of {current['title']}",
            tags=tuple(current["tags"]),
        )

    def set_favorite(self, scenario_id: str, favorite: bool) -> dict[str, Any]:
        self.get_scenario(scenario_id)
        with self._transaction() as connection:
            connection.execute(
                "UPDATE scenarios SET favorite = ?, updated_at = ? WHERE scenario_id = ?",
                (int(favorite), _now(), scenario_id),
            )
        return self.get_scenario(scenario_id)

    def delete_scenario(self, scenario_id: str) -> None:
        self.get_scenario(scenario_id)
        with self._transaction() as connection:
            connection.execute("DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,))

    def save_analysis(
        self,
        scenario_id: str,
        result: AnalysisResult,
        *,
        raw_scenario: ScenarioSpec,
        execution_ms: float,
        status: str = "completed",
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = self.get_scenario(scenario_id)
        analysis_id = uuid4().hex
        now = _now()
        output = result.to_json()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs
                    (analysis_id, scenario_id, revision_no, raw_scenario_json,
                     normalized_scenario_json, evidence_json, output_json,
                     rules_engine_version, analysis_version, random_seed,
                     execution_ms, status, error_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    scenario_id,
                    scenario["revisionNo"],
                    raw_scenario.to_json(),
                    raw_scenario.to_json(),
                    result.evidence.to_json(),
                    output,
                    result.rules_engine_version,
                    result.analysis_version,
                    result.equity.random_seed if result.equity else None,
                    execution_ms,
                    status,
                    json.dumps(error) if error else None,
                    now,
                ),
            )
        return self.get_analysis(analysis_id)

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM analysis_runs WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            raise StoreNotFound(analysis_id)
        return _analysis_record(row)

    def list_analyses(self, scenario_id: str) -> list[dict[str, Any]]:
        self.get_scenario(scenario_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM analysis_runs WHERE scenario_id = ? ORDER BY created_at DESC",
                (scenario_id,),
            ).fetchall()
        return [_analysis_record(row) for row in rows]

    def _initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self._lock:
            self._connection.executescript(schema_path.read_text(encoding="utf-8"))
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, _now()),
            )
            self._connection.commit()

    def _insert_revision(self, connection, scenario_id: str, scenario: ScenarioSpec, revision_no: int, now: str):
        serialized = scenario.to_json()
        connection.execute(
            """
            INSERT INTO scenario_revisions
                (scenario_id, revision_no, scenario_json, scenario_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scenario_id, revision_no, serialized, _hash(serialized), now),
        )

    class _Transaction:
        def __init__(self, store: SQLiteStore):
            self.store = store

        def __enter__(self):
            self.store._lock.acquire()
            return self.store._connection

        def __exit__(self, exc_type, exc, traceback):
            if exc_type is None:
                self.store._connection.commit()
            else:
                self.store._connection.rollback()
            self.store._lock.release()

    def _transaction(self):
        return self._Transaction(self)


def _scenario_record(row: sqlite3.Row) -> dict[str, Any]:
    scenario = ScenarioSpec.from_json(row["scenario_json"])
    return {
        "scenarioId": row["scenario_id"],
        "title": row["title"],
        "scenario": scenario,
        "scenarioHash": row["scenario_hash"],
        "tags": tuple(json.loads(row["tags_json"])),
        "favorite": bool(row["favorite"]),
        "revisionNo": row["current_revision"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }

def _analysis_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "analysisId": row["analysis_id"],
        "scenarioId": row["scenario_id"],
        "revisionNo": row["revision_no"],
        "output": json.loads(row["output_json"]) if row["output_json"] else None,
        "evidence": json.loads(row["evidence_json"]) if row["evidence_json"] else None,
        "rulesEngineVersion": row["rules_engine_version"],
        "analysisVersion": row["analysis_version"],
        "randomSeed": row["random_seed"],
        "executionMs": row["execution_ms"],
        "status": row["status"],
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
        "createdAt": row["created_at"],
    }


def _hash(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()
