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
from poker_coach.learning.models import (
    LearningProfile,
    PracticeAttempt,
    PracticeOutcome,
    ValidatedPractice,
)
from poker_coach.strategy.models import StrategyArtifact


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
        raw_scenario_json: str | None = None,
    ) -> dict[str, Any]:
        scenario_id = uuid4().hex
        now = _now()
        serialized = scenario.to_json()
        raw_serialized = raw_scenario_json if raw_scenario_json is not None else serialized
        scenario_hash = _hash(serialized)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO scenarios
                    (scenario_id, title, raw_scenario_json, scenario_json, scenario_hash,
                     tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (scenario_id, title, raw_serialized, serialized, scenario_hash,
                 json.dumps(sorted(tags)), now, now),
            )
            self._insert_revision(
                connection, scenario_id, scenario, 1, now, raw_scenario_json=raw_serialized
            )
            self._insert_range_versions(connection, scenario, now)
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

    def get_scenario_revision(self, scenario_id: str, revision_no: int) -> dict[str, Any]:
        if revision_no < 1:
            raise StoreNotFound(f"{scenario_id}:revision:{revision_no}")
        with self._lock:
            row = self._connection.execute(
                """
                SELECT scenario_id, revision_no, raw_scenario_json, scenario_json,
                       scenario_hash, created_at
                FROM scenario_revisions
                WHERE scenario_id = ? AND revision_no = ?
                """,
                (scenario_id, revision_no),
            ).fetchone()
        if row is None:
            raise StoreNotFound(f"{scenario_id}:revision:{revision_no}")
        return _revision_record(row)

    def list_scenario_revisions(self, scenario_id: str) -> list[dict[str, Any]]:
        self.get_scenario(scenario_id)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT scenario_id, revision_no, raw_scenario_json, scenario_json,
                       scenario_hash, created_at
                FROM scenario_revisions
                WHERE scenario_id = ?
                ORDER BY revision_no DESC
                """,
                (scenario_id,),
            ).fetchall()
        return [_revision_record(row) for row in rows]

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
        raw_scenario_json: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        now = _now()
        serialized = scenario.to_json()
        raw_serialized = raw_scenario_json if raw_scenario_json is not None else serialized
        scenario_hash = _hash(serialized)
        next_revision = int(current["revisionNo"]) + 1
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE scenarios
                SET title = ?, raw_scenario_json = ?, scenario_json = ?, scenario_hash = ?,
                    tags_json = ?, updated_at = ?
                WHERE scenario_id = ?
                """,
                (
                    title if title is not None else current["title"],
                    raw_serialized,
                    serialized,
                    scenario_hash,
                    json.dumps(sorted(tags if tags is not None else current["tags"])),
                    now,
                    scenario_id,
                ),
            )
            self._insert_revision(
                connection, scenario_id, scenario, next_revision, now,
                raw_scenario_json=raw_serialized,
            )
            self._insert_range_versions(connection, scenario, now)
        return self.get_scenario(scenario_id)

    def copy_scenario(self, scenario_id: str, *, title: str | None = None) -> dict[str, Any]:
        current = self.get_scenario(scenario_id)
        return self.create_scenario(
            current["scenario"],
            title=title or f"Copy of {current['title']}",
            tags=tuple(current["tags"]),
            raw_scenario_json=current.get("rawScenarioJson"),
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
        raw_scenario_json: str | None = None,
        revision_no: int | None = None,
        execution_ms: float,
        status: str = "completed",
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = (
            self.get_scenario_revision(scenario_id, revision_no)
            if revision_no is not None
            else self.get_scenario(scenario_id)
        )
        analysis_id = uuid4().hex
        now = _now()
        output = result.to_json()
        raw_serialized = (
            raw_scenario_json
            if raw_scenario_json is not None
            else scenario.get("rawScenarioJson", raw_scenario.to_json())
        )
        normalized_serialized = scenario["scenario"].to_json()
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
                    raw_serialized,
                    normalized_serialized,
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
            connection.executemany(
                """
                INSERT INTO evidence_items
                    (analysis_id, evidence_id, kind, value_json, unit, source_level, source_version, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        analysis_id,
                        item.evidence_id,
                        item.kind,
                        json.dumps(
                            item.model_dump(mode="json")["value"],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        item.unit,
                        item.source_level.value,
                        item.source_version,
                        item.description,
                    )
                    for item in result.evidence.items
                ],
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

    def register_strategy_artifacts(self, artifacts: tuple[StrategyArtifact, ...]) -> None:
        with self._transaction() as connection:
            for artifact in artifacts:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO strategy_artifacts
                        (artifact_id, artifact_version, artifact_json, source_level, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.artifact_id,
                        artifact.version,
                        artifact.to_json(),
                        artifact.source_level.value,
                        _now(),
                    ),
                )

    def get_or_create_profile(self, profile_id: str | None = None) -> LearningProfile:
        profile_id = profile_id or uuid4().hex
        with self._lock:
            row = self._connection.execute(
                "SELECT profile_json FROM learning_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if row is not None:
            return LearningProfile.model_validate(json.loads(row["profile_json"]))
        profile = LearningProfile(profileId=profile_id, updatedAt=_now())
        with self._transaction() as connection:
            now = _now()
            connection.execute(
                """
                INSERT INTO learning_profiles(profile_id, profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (profile_id, profile.to_json(), now, now),
            )
        return profile

    def get_profile(self, profile_id: str) -> LearningProfile:
        with self._lock:
            row = self._connection.execute(
                "SELECT profile_json FROM learning_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise StoreNotFound(profile_id)
        return LearningProfile.model_validate(json.loads(row["profile_json"]))

    def save_profile(self, profile: LearningProfile) -> LearningProfile:
        self.get_or_create_profile(profile.profile_id)
        serialized = profile.to_json()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE learning_profiles SET profile_json = ?, updated_at = ? WHERE profile_id = ?",
                (serialized, profile.updated_at, profile.profile_id),
            )
        return profile

    def delete_profile(self, profile_id: str) -> None:
        with self._lock:
            exists = self._connection.execute(
                "SELECT 1 FROM learning_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        if exists is None:
            raise StoreNotFound(profile_id)
        with self._transaction() as connection:
            connection.execute("DELETE FROM learning_profiles WHERE profile_id = ?", (profile_id,))

    def save_teaching_session(
        self,
        response: dict[str, Any],
        *,
        teacher_version: str,
        prompt_version: str | None = None,
        depth: str,
        user_question: str | None = None,
        profile_id: str | None = None,
        scenario_id: str | None = None,
        analysis_id: str | None = None,
    ) -> dict[str, Any]:
        session_id = uuid4().hex
        created_at = _now()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO teaching_sessions
                    (session_id, profile_id, scenario_id, analysis_id, teacher_version,
                     prompt_version, depth, user_question, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    profile_id,
                    scenario_id,
                    analysis_id,
                    teacher_version,
                    prompt_version or response.get("responseVersion", "1"),
                    depth,
                    user_question,
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            if user_question:
                connection.execute(
                    """
                    INSERT INTO teaching_messages(message_id, session_id, role, content_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        session_id,
                        "user",
                        json.dumps({"text": user_question}, ensure_ascii=False, sort_keys=True),
                        created_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO teaching_messages(message_id, session_id, role, content_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    session_id,
                    "assistant",
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
        return {
            "sessionId": session_id,
            "teacherVersion": teacher_version,
            "depth": depth,
            "createdAt": created_at,
        }

    def save_practice_question(self, question: ValidatedPractice) -> dict[str, Any]:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO practice_questions
                    (question_id, profile_id, source_scenario_id, source_analysis_id,
                     question_json, expected_action, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question.question_id,
                    question.profile_id,
                    question.source_scenario_id,
                    question.source_analysis_id,
                    question.to_json(),
                    question.expected_action,
                    json.dumps(
                        [reference.to_dict() for reference in question.expected_evidence_references],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    question.created_at,
                ),
            )
        return _practice_question_record(question)

    def get_practice_question(self, question_id: str) -> ValidatedPractice:
        with self._lock:
            row = self._connection.execute(
                "SELECT question_json FROM practice_questions WHERE question_id = ?",
                (question_id,),
            ).fetchone()
        if row is None:
            raise StoreNotFound(question_id)
        return ValidatedPractice.model_validate(json.loads(row["question_json"]))

    def save_practice_outcome(
        self,
        question: ValidatedPractice,
        outcome: PracticeOutcome,
    ) -> dict[str, Any]:
        profile = outcome.profile
        self.get_or_create_profile(profile.profile_id)
        now = outcome.attempt.created_at
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO practice_attempts
                    (attempt_id, question_id, selected_action, correct, rationale, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.attempt.attempt_id,
                    question.question_id,
                    outcome.attempt.selected_action,
                    int(outcome.attempt.correct),
                    outcome.attempt.rationale,
                    json.dumps(
                        [reference.to_dict() for reference in outcome.attempt.evidence_references],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            connection.execute(
                "UPDATE learning_profiles SET profile_json = ?, updated_at = ? WHERE profile_id = ?",
                (profile.to_json(), profile.updated_at, profile.profile_id),
            )
            for concept in question.concept_tags:
                connection.execute(
                    """
                    INSERT INTO concept_progress(profile_id, concept_tag, attempts, correct, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, concept_tag) DO UPDATE SET
                        attempts = excluded.attempts,
                        correct = excluded.correct,
                        updated_at = excluded.updated_at
                    """,
                    (
                        profile.profile_id,
                        concept,
                        profile.concept_attempts.get(concept, 0),
                        profile.concept_correct.get(concept, 0),
                        profile.updated_at,
                    ),
                )
            if question.mistake_tag and not outcome.attempt.correct:
                connection.execute(
                    """
                    INSERT INTO mistake_records
                        (record_id, profile_id, scenario_id, analysis_id, mistake_tag, street, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        profile.profile_id,
                        question.source_scenario_id,
                        question.source_analysis_id,
                        question.mistake_tag,
                        question.scenario.decision_point.street.value,
                        now,
                    ),
                )
        return {
            "attempt": outcome.attempt.to_dict(),
            "expectedAction": outcome.expected_action,
            "explanation": outcome.explanation,
            "evidenceReferences": [reference.to_dict() for reference in outcome.evidence_references],
            "profile": profile.to_dict(),
        }

    def _initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self._lock:
            self._connection.executescript(schema_path.read_text(encoding="utf-8"))
            self._migrate_strategy_artifacts()
            self._migrate_raw_scenario_snapshots()
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, _now()),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, _now()),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, _now()),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, _now()),
            )
            self._connection.commit()

    def _migrate_strategy_artifacts(self) -> None:
        columns = self._connection.execute("PRAGMA table_info(strategy_artifacts)").fetchall()
        primary_key_columns = [row[1] for row in columns if row[5]]
        if primary_key_columns == ["artifact_id", "artifact_version"]:
            return
        self._connection.execute(
            """
            CREATE TABLE strategy_artifacts_v3 (
                artifact_id TEXT NOT NULL,
                artifact_version TEXT NOT NULL,
                artifact_json TEXT NOT NULL,
                source_level TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (artifact_id, artifact_version)
            )
            """
        )
        self._connection.execute(
            """
            INSERT OR IGNORE INTO strategy_artifacts_v3
                (artifact_id, artifact_version, artifact_json, source_level, created_at)
            SELECT artifact_id, artifact_version, artifact_json, source_level, created_at
            FROM strategy_artifacts
            """
        )
        self._connection.execute("DROP TABLE strategy_artifacts")
        self._connection.execute("ALTER TABLE strategy_artifacts_v3 RENAME TO strategy_artifacts")

    def _migrate_raw_scenario_snapshots(self) -> None:
        for table in ("scenarios", "scenario_revisions"):
            columns = {
                row[1]
                for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "raw_scenario_json" not in columns:
                self._connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN raw_scenario_json TEXT"
                )
                self._connection.execute(
                    f"UPDATE {table} SET raw_scenario_json = scenario_json "
                    "WHERE raw_scenario_json IS NULL"
                )

    def _insert_revision(
        self,
        connection,
        scenario_id: str,
        scenario: ScenarioSpec,
        revision_no: int,
        now: str,
        *,
        raw_scenario_json: str | None = None,
    ):
        serialized = scenario.to_json()
        raw_serialized = raw_scenario_json if raw_scenario_json is not None else serialized
        connection.execute(
            """
            INSERT INTO scenario_revisions
                (scenario_id, revision_no, raw_scenario_json, scenario_json, scenario_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scenario_id, revision_no, raw_serialized, serialized, _hash(serialized), now),
        )

    def _insert_range_versions(self, connection, scenario: ScenarioSpec, now: str) -> None:
        for range_spec in (scenario.hero_range, scenario.villain_range):
            if range_spec is None:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO range_versions
                    (range_id, range_version, range_json, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    range_spec.range_id,
                    range_spec.version,
                    range_spec.to_json(),
                    range_spec.source.value,
                    now,
                ),
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
    raw_scenario_json = row["raw_scenario_json"] or row["scenario_json"]
    return {
        "scenarioId": row["scenario_id"],
        "title": row["title"],
        "rawScenario": json.loads(raw_scenario_json),
        "rawScenarioJson": raw_scenario_json,
        "scenario": scenario,
        "scenarioHash": row["scenario_hash"],
        "tags": tuple(json.loads(row["tags_json"])),
        "favorite": bool(row["favorite"]),
        "revisionNo": row["current_revision"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _revision_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    raw_scenario_json = row["raw_scenario_json"] or row["scenario_json"]
    return {
        "scenarioId": row["scenario_id"],
        "revisionNo": row["revision_no"],
        "rawScenario": json.loads(raw_scenario_json),
        "rawScenarioJson": raw_scenario_json,
        "scenario": ScenarioSpec.from_json(row["scenario_json"]),
        "scenarioHash": row["scenario_hash"],
        "createdAt": row["created_at"],
    }

def _analysis_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "analysisId": row["analysis_id"],
        "scenarioId": row["scenario_id"],
        "revisionNo": row["revision_no"],
        "rawScenario": json.loads(row["raw_scenario_json"]),
        "normalizedScenario": json.loads(row["normalized_scenario_json"]),
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


def _practice_question_record(question: ValidatedPractice) -> dict[str, Any]:
    return {
        "questionId": question.question_id,
        "profileId": question.profile_id,
        "sourceScenarioId": question.source_scenario_id,
        "sourceAnalysisId": question.source_analysis_id,
        "scenario": question.scenario.to_dict(),
        "prompt": question.prompt,
        "conceptTags": list(question.concept_tags),
        "mistakeTag": question.mistake_tag,
        "createdAt": question.created_at,
    }


def _hash(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()
