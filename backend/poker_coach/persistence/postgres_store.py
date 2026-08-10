"""Optional PostgreSQL repository with the same logical contract as SQLiteStore.

The psycopg import is deliberately lazy: local development remains SQLite-only,
while production can select this store with POKER_COACH_DATABASE_URL.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from poker_coach.analysis.models import AnalysisResult
from poker_coach.domain.models import ScenarioSpec
from poker_coach.learning.models import LearningProfile, PracticeOutcome, ValidatedPractice
from poker_coach.strategy.models import StrategyArtifact

from .sqlite_store import (
    StoreNotFound,
    _analysis_record,
    _practice_question_record,
    _revision_record,
    _scenario_record,
)


class PostgresUnavailable(RuntimeError):
    """Raised when PostgreSQL was requested but its optional driver is absent."""


class PostgresStore:
    """DB-API repository for PostgreSQL 10+ using psycopg 3.

    JSON snapshots intentionally match SQLiteStore so ScenarioSpec and API
    contracts remain database-neutral. Business rules never run in this class.
    """

    def __init__(self, dsn: str, *, connection=None):
        self.dsn = dsn
        self._owns_connection = connection is None
        if connection is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - exercised in deployment
                raise PostgresUnavailable(
                    "PostgreSQL requires the optional dependency 'psycopg[binary]'"
                ) from exc
            connection = psycopg.connect(dsn)
        self._connection = connection
        self._initialize()

    def close(self) -> None:
        if self._owns_connection:
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
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO scenarios (scenario_id, title, raw_scenario_json, scenario_json, scenario_hash, tags_json, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (scenario_id, title, raw_serialized, serialized, _hash(serialized), json.dumps(sorted(tags)), now, now),
            )
            self._insert_revision(cursor, scenario_id, scenario, 1, now, raw_scenario_json=raw_serialized)
            self._insert_range_versions(cursor, scenario, now)
        return self.get_scenario(scenario_id)

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        row = self._fetchone(
            """
            SELECT s.*, COALESCE((SELECT MAX(r.revision_no) FROM scenario_revisions r
                                  WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
            FROM scenarios s WHERE s.scenario_id = %s
            """,
            (scenario_id,),
        )
        if row is None:
            raise StoreNotFound(scenario_id)
        return _scenario_record(row)

    def get_scenario_revision(self, scenario_id: str, revision_no: int) -> dict[str, Any]:
        if revision_no < 1:
            raise StoreNotFound(f"{scenario_id}:revision:{revision_no}")
        row = self._fetchone(
            """
            SELECT scenario_id, revision_no, raw_scenario_json, scenario_json,
                   scenario_hash, created_at
            FROM scenario_revisions
            WHERE scenario_id = %s AND revision_no = %s
            """,
            (scenario_id, revision_no),
        )
        if row is None:
            raise StoreNotFound(f"{scenario_id}:revision:{revision_no}")
        return _revision_record(row)

    def list_scenario_revisions(self, scenario_id: str) -> list[dict[str, Any]]:
        self.get_scenario(scenario_id)
        rows = self._fetchall(
            """
            SELECT scenario_id, revision_no, raw_scenario_json, scenario_json,
                   scenario_hash, created_at
            FROM scenario_revisions
            WHERE scenario_id = %s
            ORDER BY revision_no DESC
            """,
            (scenario_id,),
        )
        return [_revision_record(row) for row in rows]

    def list_scenarios(self, *, query: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        if query:
            rows = self._fetchall(
                """
                SELECT s.*, COALESCE((SELECT MAX(r.revision_no) FROM scenario_revisions r
                                      WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
                FROM scenarios s
                WHERE title ILIKE %s OR scenario_json ILIKE %s OR tags_json ILIKE %s
                ORDER BY updated_at DESC LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
        else:
            rows = self._fetchall(
                """
                SELECT s.*, COALESCE((SELECT MAX(r.revision_no) FROM scenario_revisions r
                                      WHERE r.scenario_id = s.scenario_id), 1) AS current_revision
                FROM scenarios s ORDER BY updated_at DESC LIMIT %s
                """,
                (limit,),
            )
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
        next_revision = int(current["revisionNo"]) + 1
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE scenarios SET title = %s, raw_scenario_json = %s, scenario_json = %s, scenario_hash = %s, tags_json = %s, updated_at = %s WHERE scenario_id = %s",
                (
                    title if title is not None else current["title"],
                    raw_serialized,
                    serialized,
                    _hash(serialized),
                    json.dumps(sorted(tags if tags is not None else current["tags"])),
                    now,
                    scenario_id,
                ),
            )
            self._insert_revision(cursor, scenario_id, scenario, next_revision, now, raw_scenario_json=raw_serialized)
            self._insert_range_versions(cursor, scenario, now)
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
        with self._transaction() as cursor:
            cursor.execute("UPDATE scenarios SET favorite = %s, updated_at = %s WHERE scenario_id = %s", (favorite, _now(), scenario_id))
        return self.get_scenario(scenario_id)

    def delete_scenario(self, scenario_id: str) -> None:
        self.get_scenario(scenario_id)
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM scenarios WHERE scenario_id = %s", (scenario_id,))

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
        raw_serialized = (
            raw_scenario_json
            if raw_scenario_json is not None
            else scenario.get("rawScenarioJson", raw_scenario.to_json())
        )
        normalized_serialized = scenario["scenario"].to_json()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO analysis_runs
                    (analysis_id, scenario_id, revision_no, raw_scenario_json, normalized_scenario_json,
                     evidence_json, output_json, rules_engine_version, analysis_version, random_seed,
                     execution_ms, status, error_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    analysis_id,
                    scenario_id,
                    scenario["revisionNo"],
                    raw_serialized,
                    normalized_serialized,
                    result.evidence.to_json(),
                    result.to_json(),
                    result.rules_engine_version,
                    result.analysis_version,
                    result.equity.random_seed if result.equity else None,
                    execution_ms,
                    status,
                    json.dumps(error) if error else None,
                    now,
                ),
            )
            for item in result.evidence.items:
                cursor.execute(
                    """
                    INSERT INTO evidence_items
                        (analysis_id, evidence_id, kind, value_json, unit, source_level, source_version, description)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
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
                    ),
                )
        return self.get_analysis(analysis_id)

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM analysis_runs WHERE analysis_id = %s", (analysis_id,))
        if row is None:
            raise StoreNotFound(analysis_id)
        return _analysis_record(row)

    def list_analyses(self, scenario_id: str) -> list[dict[str, Any]]:
        self.get_scenario(scenario_id)
        rows = self._fetchall("SELECT * FROM analysis_runs WHERE scenario_id = %s ORDER BY created_at DESC", (scenario_id,))
        return [_analysis_record(row) for row in rows]

    def register_strategy_artifacts(self, artifacts: tuple[StrategyArtifact, ...]) -> None:
        with self._transaction() as cursor:
            for artifact in artifacts:
                cursor.execute(
                    """
                    INSERT INTO strategy_artifacts (artifact_id, artifact_version, artifact_json, source_level, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_id, artifact_version) DO UPDATE SET
                        artifact_json = EXCLUDED.artifact_json,
                        source_level = EXCLUDED.source_level,
                        created_at = EXCLUDED.created_at
                    """,
                    (artifact.artifact_id, artifact.version, artifact.to_json(), artifact.source_level.value, _now()),
                )

    def get_or_create_profile(self, profile_id: str | None = None) -> LearningProfile:
        profile_id = profile_id or uuid4().hex
        profile = self._profile_or_none(profile_id)
        if profile is not None:
            return profile
        now = _now()
        profile = LearningProfile(profileId=profile_id, updatedAt=now)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO learning_profiles (profile_id, profile_json, created_at, updated_at) VALUES (%s, %s, %s, %s) ON CONFLICT (profile_id) DO NOTHING",
                (profile_id, profile.to_json(), now, now),
            )
        return self._profile_or_none(profile_id) or profile

    def get_profile(self, profile_id: str) -> LearningProfile:
        profile = self._profile_or_none(profile_id)
        if profile is None:
            raise StoreNotFound(profile_id)
        return profile

    def delete_profile(self, profile_id: str) -> None:
        self.get_profile(profile_id)
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM learning_profiles WHERE profile_id = %s", (profile_id,))

    def save_teaching_session(self, response: dict[str, Any], *, teacher_version: str, prompt_version: str | None = None, depth: str, user_question: str | None = None, profile_id: str | None = None, scenario_id: str | None = None, analysis_id: str | None = None) -> dict[str, Any]:
        session_id = uuid4().hex
        created_at = _now()
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO teaching_sessions (session_id, profile_id, scenario_id, analysis_id, teacher_version, prompt_version, depth, user_question, response_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (session_id, profile_id, scenario_id, analysis_id, teacher_version, prompt_version or response.get("responseVersion", "1"), depth, user_question, json.dumps(response, ensure_ascii=False, sort_keys=True), created_at),
            )
            if user_question:
                cursor.execute(
                    "INSERT INTO teaching_messages (message_id, session_id, role, content_json, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (uuid4().hex, session_id, "user", json.dumps({"text": user_question}, ensure_ascii=False, sort_keys=True), created_at),
                )
            cursor.execute(
                "INSERT INTO teaching_messages (message_id, session_id, role, content_json, created_at) VALUES (%s, %s, %s, %s, %s)",
                (uuid4().hex, session_id, "assistant", json.dumps(response, ensure_ascii=False, sort_keys=True), created_at),
            )
        return {"sessionId": session_id, "teacherVersion": teacher_version, "depth": depth, "createdAt": created_at}

    def save_practice_question(self, question: ValidatedPractice) -> dict[str, Any]:
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO practice_questions (question_id, profile_id, source_scenario_id, source_analysis_id, question_json, expected_action, evidence_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    question.question_id,
                    question.profile_id,
                    question.source_scenario_id,
                    question.source_analysis_id,
                    question.to_json(),
                    question.expected_action,
                    json.dumps([reference.to_dict() for reference in question.expected_evidence_references], ensure_ascii=False, sort_keys=True),
                    question.created_at,
                ),
            )
        return _practice_question_record(question)

    def get_practice_question(self, question_id: str) -> ValidatedPractice:
        row = self._fetchone("SELECT question_json FROM practice_questions WHERE question_id = %s", (question_id,))
        if row is None:
            raise StoreNotFound(question_id)
        return ValidatedPractice.model_validate(json.loads(row["question_json"]))

    def save_practice_outcome(self, question: ValidatedPractice, outcome: PracticeOutcome) -> dict[str, Any]:
        profile = outcome.profile
        self.get_profile(profile.profile_id)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO practice_attempts (attempt_id, question_id, selected_action, correct, rationale, evidence_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (outcome.attempt.attempt_id, question.question_id, outcome.attempt.selected_action, outcome.attempt.correct, outcome.attempt.rationale, json.dumps([reference.to_dict() for reference in outcome.attempt.evidence_references], ensure_ascii=False, sort_keys=True), outcome.attempt.created_at),
            )
            cursor.execute("UPDATE learning_profiles SET profile_json = %s, updated_at = %s WHERE profile_id = %s", (profile.to_json(), profile.updated_at, profile.profile_id))
            for concept in question.concept_tags:
                cursor.execute(
                    """
                    INSERT INTO concept_progress (profile_id, concept_tag, attempts, correct, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (profile_id, concept_tag) DO UPDATE SET
                        attempts = EXCLUDED.attempts, correct = EXCLUDED.correct, updated_at = EXCLUDED.updated_at
                    """,
                    (profile.profile_id, concept, profile.concept_attempts.get(concept, 0), profile.concept_correct.get(concept, 0), profile.updated_at),
                )
            if question.mistake_tag and not outcome.attempt.correct:
                cursor.execute(
                    "INSERT INTO mistake_records (record_id, profile_id, scenario_id, analysis_id, mistake_tag, street, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (uuid4().hex, profile.profile_id, question.source_scenario_id, question.source_analysis_id, question.mistake_tag, question.scenario.decision_point.street.value, outcome.attempt.created_at),
                )
        return {
            "attempt": outcome.attempt.to_dict(),
            "expectedAction": outcome.expected_action,
            "explanation": outcome.explanation,
            "evidenceReferences": [reference.to_dict() for reference in outcome.evidence_references],
            "profile": profile.to_dict(),
        }

    def _profile_or_none(self, profile_id: str) -> LearningProfile | None:
        row = self._fetchone("SELECT profile_json FROM learning_profiles WHERE profile_id = %s", (profile_id,))
        return LearningProfile.model_validate(json.loads(row["profile_json"])) if row else None

    def _initialize(self) -> None:
        schema = Path(__file__).with_name("postgres_schema.sql").read_text(encoding="utf-8")
        with self._transaction() as cursor:
            # psycopg intentionally treats one execute call as one statement.
            # The checked-in schema is a simple migration script, so split on
            # statement terminators instead of relying on SQLite-style batch
            # execution or driver-specific multi-statement behavior.
            for statement in schema.split(";\n"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            for version in (1, 2, 3):
                cursor.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                    (version, _now()),
                )
            for table in ("scenarios", "scenario_revisions"):
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS raw_scenario_json TEXT"
                )
                cursor.execute(
                    f"UPDATE {table} SET raw_scenario_json = scenario_json "
                    "WHERE raw_scenario_json IS NULL"
                )
            cursor.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                (4, _now()),
            )

    def _insert_revision(
        self,
        cursor,
        scenario_id: str,
        scenario: ScenarioSpec,
        revision_no: int,
        now: str,
        *,
        raw_scenario_json: str | None = None,
    ) -> None:
        serialized = scenario.to_json()
        raw_serialized = raw_scenario_json if raw_scenario_json is not None else serialized
        cursor.execute(
            "INSERT INTO scenario_revisions (scenario_id, revision_no, raw_scenario_json, scenario_json, scenario_hash, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (scenario_id, revision_no, raw_serialized, serialized, _hash(serialized), now),
        )

    def _insert_range_versions(self, cursor, scenario: ScenarioSpec, now: str) -> None:
        for range_spec in (scenario.hero_range, scenario.villain_range):
            if range_spec is None:
                continue
            cursor.execute(
                """
                INSERT INTO range_versions (range_id, range_version, range_json, source, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (range_id, range_version) DO UPDATE SET
                    range_json = EXCLUDED.range_json,
                    source = EXCLUDED.source,
                    created_at = EXCLUDED.created_at
                """,
                (
                    range_spec.range_id,
                    range_spec.version,
                    range_spec.to_json(),
                    range_spec.source.value,
                    now,
                ),
            )

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

    def _fetchone(self, query: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return _row_to_dict(cursor, row)
        finally:
            cursor.close()

    def _fetchall(self, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(query, tuple(params))
            return [_row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()


def _row_to_dict(cursor, row) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    columns = [
        description.name if hasattr(description, "name") else description[0]
        for description in cursor.description
    ]
    return dict(zip(columns, row))


def _hash(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()
