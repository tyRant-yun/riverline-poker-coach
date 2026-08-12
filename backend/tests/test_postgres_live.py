"""Live PostgreSQL deployment regression tests.

These tests require a real PostgreSQL instance and are skipped by default,
so the normal suite stays green without one. Enable them for the deployment
regression:

    set POKER_COACH_TEST_PG_URL=postgresql://coach:coach@127.0.0.1:55432/coach_test
    py -3.13 -m pytest backend/tests/test_postgres_live.py -v

They verify the PostgresStore against a live server end-to-end: schema
initialization and migrations, scenario/revision CRUD parity with SQLite,
analysis history and evidence persistence, learning records, and the full
FastAPI flow over PostgreSQL.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from poker_coach.analysis import analyze_scenario
from poker_coach.api import AppConfig, create_app
from poker_coach.domain.models import ScenarioSpec
from poker_coach.learning import LearningService
from poker_coach.persistence import (
    PostgresHandEventStore,
    PostgresProjectionStore,
    PostgresStore,
    SQLiteStore,
)
from poker_coach.rules import PokerKitAdapter
from poker_coach.simulator import (
    ExpectedSequenceConflict,
    HandEventV1,
    OutboxDispatcher,
    OutboxIntentV1,
    ProjectionIdentityV1,
    ProjectionRunner,
    RawHandEventV1,
)

PG_URL = os.getenv("POKER_COACH_TEST_PG_URL")

pytestmark = [
    pytest.mark.live,
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
    pytest.mark.skipif(
        not PG_URL, reason="POKER_COACH_TEST_PG_URL is not set; no live PostgreSQL"
    ),
]

# Fields that are random or time-based per store and never expected to match.
_RANDOM_FIELDS = {
    "scenarioId",
    "analysisId",
    "profileId",
    "questionId",
    "attemptId",
    "createdAt",
    "updatedAt",
}


def scenario_at_flop() -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "villainHoleCards": ["Qh", "Jc"],
            "board": ["2c", "7d", "Jh"],
            "actionHistory": [
                {
                    "actionId": "call",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "flop",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 0,
                    "actionType": "deal_flop",
                },
            ],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
            "assumptions": {},
        }
    )


def _normalize(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in _RANDOM_FIELDS}


@pytest.fixture()
def pg_store():
    """Fresh PostgreSQL database with all public tables dropped."""
    import psycopg

    # Short connect timeout: a stale POKER_COACH_TEST_PG_URL must fail fast
    # instead of hanging the whole suite.
    with psycopg.connect(PG_URL, autocommit=True, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    store = PostgresStore(PG_URL)
    yield store
    store.close()


def test_live_schema_initialization_and_migrations(pg_store):
    with pg_store._connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        migrations = [row[0] for row in cursor.fetchall()]
    assert {
        "scenarios",
        "scenario_revisions",
        "analysis_runs",
        "evidence_items",
        "learning_profiles",
        "practice_questions",
        "practice_attempts",
        "teaching_sessions",
        "concept_progress",
        "mistake_records",
        "strategy_artifacts",
    } <= tables
    assert migrations == [1, 2, 3, 4]


def test_live_hand_event_append_round_trip_and_same_expected_sequence_race(pg_store):
    first = PostgresHandEventStore(PG_URL)
    second = PostgresHandEventStore(PG_URL)
    barrier = Barrier(2)

    def event(event_id: str) -> RawHandEventV1:
        return RawHandEventV1.from_event(
            HandEventV1.model_validate(
                {
                    "schemaVersion": 1,
                    "eventId": event_id,
                    "handId": "live-session:hand:1",
                    "sequence": 1,
                    "timestamp": "2026-08-12T00:00:01Z",
                    "source": "fixture",
                    "provenance": {
                        "producer": "riverline-live-tests",
                        "producerVersion": "1.0.0",
                        "correlationId": "live-session",
                    },
                    "payload": {
                        "kind": "hand_started",
                        "ruleset": "nlhe",
                        "tableSize": 2,
                        "buttonSeat": 0,
                        "smallBlind": 50,
                        "bigBlind": 100,
                        "startingStacks": {"0": 10_000, "1": 10_000},
                        "rngSeed": 20260812,
                    },
                }
            )
        )

    def append(store, event_id):
        barrier.wait()
        try:
            return store.append(
                hand_id="live-session:hand:1",
                expected_sequence=0,
                events=(event(event_id),),
            )
        except ExpectedSequenceConflict as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                executor.map(append, (first, second), ("evt-live-1", "evt-live-2"))
            )

        assert sum(isinstance(item, ExpectedSequenceConflict) for item in outcomes) == 1
        stored = first.read("live-session:hand:1")
        assert len(stored) == 1
        assert stored[0].event.provenance.correlation_id == "live-session"
    finally:
        first.close()
        second.close()


def test_live_projection_rebuild_and_transactional_outbox_dispatch(pg_store):
    event_store = PostgresHandEventStore(PG_URL)
    projection_store = PostgresProjectionStore(PG_URL)
    event = RawHandEventV1.from_event(
        HandEventV1.model_validate(
            {
                "schemaVersion": 1,
                "eventId": "evt-live-recovery",
                "handId": "live-session:hand:recovery",
                "sequence": 1,
                "timestamp": "2026-08-12T00:00:01Z",
                "source": "fixture",
                "provenance": {
                    "producer": "riverline-live-tests",
                    "producerVersion": "1.0.0",
                    "correlationId": "live-session",
                },
                "payload": {
                    "kind": "hand_started",
                    "ruleset": "nlhe",
                    "tableSize": 2,
                    "buttonSeat": 0,
                    "smallBlind": 50,
                    "bigBlind": 100,
                    "startingStacks": {"0": 10_000, "1": 10_000},
                    "rngSeed": 20260812,
                },
            }
        )
    )
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )
    identity = ProjectionIdentityV1(
        projection_name="live_event_ids",
        projection_version=1,
    )

    try:
        event_store.append(
            hand_id=event.event.hand_id,
            expected_sequence=0,
            events=(event,),
            outbox_intents=(intent,),
        )
        runner = ProjectionRunner(
            event_store,
            projection_store,
            identity,
            lambda snapshot, item: {
                "eventIds": [*(snapshot or {}).get("eventIds", []), item.event_id]
            },
        )
        incremental = runner.run(event.event.hand_id)
        rebuilt = runner.rebuild(event.event.hand_id)
        delivered = []
        result = OutboxDispatcher(event_store).dispatch_once(
            worker_id="live-worker",
            dispatch=lambda message: delivered.append(message.idempotency_key),
            now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )

        assert rebuilt.payload == incremental.payload
        assert rebuilt.fingerprint == incremental.fingerprint
        assert result.dispatched_count == 1
        assert delivered == [intent.idempotency_key]
    finally:
        projection_store.close()
        event_store.close()


def test_live_scenario_crud_parity_with_sqlite(pg_store, tmp_path):
    sqlite = SQLiteStore(tmp_path / "parity.sqlite3")
    try:
        scenario = scenario_at_flop()

        def flow(store):
            created = store.create_scenario(scenario, title="flop node", tags=("pot_odds",))
            updated = store.update_scenario(
                created["scenarioId"],
                scenario,
                title="flop node v2",
                tags=("pot_odds", "spr"),
            )
            listed = store.list_scenarios()
            searched = store.list_scenarios(query="flop node v2")
            favorite = store.set_favorite(created["scenarioId"], True)
            revision_one = store.get_scenario_revision(created["scenarioId"], 1)
            revision_two = store.get_scenario_revision(created["scenarioId"], 2)
            revisions = store.list_scenario_revisions(created["scenarioId"])
            copied = store.copy_scenario(created["scenarioId"])
            store.delete_scenario(copied["scenarioId"])
            return {
                "created": _normalize(created),
                "updated": _normalize(updated),
                "listed_count": len(listed),
                "search_count": len(searched),
                "favorite": favorite["favorite"],
                "revision_one": _normalize(revision_one),
                "revision_two": _normalize(revision_two),
                "revision_count": len(revisions),
                "copy_title": copied["title"],
            }

        sqlite_result = flow(sqlite)
        postgres_result = flow(pg_store)

        assert postgres_result == sqlite_result
        assert postgres_result["updated"]["revisionNo"] == 2
        assert postgres_result["revision_count"] == 2

        # Deletion removes the scenario and cascades revisions on both stores.
        scenario_id = pg_store.list_scenarios()[0]["scenarioId"]
        pg_store.delete_scenario(scenario_id)
        with pytest.raises(Exception):
            pg_store.get_scenario(scenario_id)
    finally:
        sqlite.close()


def test_live_analysis_history_and_evidence_parity(pg_store, tmp_path):
    sqlite = SQLiteStore(tmp_path / "analysis-parity.sqlite3")
    try:
        scenario = scenario_at_flop()
        adapter = PokerKitAdapter()
        result = analyze_scenario(scenario, adapter=adapter)

        def flow(store):
            created = store.create_scenario(scenario, title="analysis target")
            saved = store.save_analysis(
                created["scenarioId"],
                result,
                raw_scenario=scenario,
                execution_ms=12.5,
            )
            listed = store.list_analyses(created["scenarioId"])
            evidence_ids = [item.evidence_id for item in result.evidence.items]
            return {
                "analysis": _normalize(saved),
                "analysis_count": len(listed),
                "evidence_ids": evidence_ids,
            }

        sqlite_result = flow(sqlite)
        postgres_result = flow(pg_store)

        assert postgres_result["analysis_count"] == 1
        assert postgres_result["evidence_ids"] == sqlite_result["evidence_ids"]
        assert postgres_result["analysis"]["revisionNo"] == 1
        assert postgres_result["analysis"]["status"] == "completed"
        # Reproducibility fields required by the goal's analysis contract.
        for key in ("rulesEngineVersion", "analysisVersion", "executionMs"):
            assert postgres_result["analysis"][key] is not None
    finally:
        sqlite.close()


def test_live_learning_profile_and_practice_parity(pg_store, tmp_path):
    sqlite = SQLiteStore(tmp_path / "learning-parity.sqlite3")
    try:
        scenario = scenario_at_flop()
        service = LearningService()

        def flow(store):
            profile = store.get_or_create_profile("profile-live")
            question = service.generate_practice(
                scenario, profile_id="profile-live", mistake_tag="pot_odds"
            )
            outcome = service.grade(
                question,
                selected_action=(
                    "fold" if question.expected_action != "fold" else "check"
                ),
                rationale="test answer",
                profile=profile,
            )
            store.save_practice_question(question)
            stored = store.get_practice_question(question.question_id)
            store.save_practice_outcome(question, outcome)
            fetched = store.get_profile("profile-live")
            store.delete_profile("profile-live")
            return {
                "question": _normalize(stored.to_dict()),
                "profile_attempts": fetched.concept_attempts,
                "profile_street_attempts": fetched.street_attempts,
            }

        sqlite_result = flow(sqlite)
        postgres_result = flow(pg_store)

        assert postgres_result == sqlite_result
        assert postgres_result["profile_attempts"]
    finally:
        sqlite.close()


def test_live_pooled_store_crud_and_parity(pg_store):
    """The pooled store must behave identically to the single-connection store."""
    from poker_coach.persistence import PooledPostgresStore

    pooled = PooledPostgresStore(PG_URL)
    try:
        scenario = scenario_at_flop()
        created = pooled.create_scenario(scenario, title="pooled", tags=("pool",))
        updated = pooled.update_scenario(
            created["scenarioId"], scenario, title="pooled v2"
        )
        assert updated["revisionNo"] == 2

        result = analyze_scenario(scenario, adapter=PokerKitAdapter())
        saved = pooled.save_analysis(
            created["scenarioId"], result, raw_scenario=scenario, execution_ms=5.0
        )
        assert saved["status"] == "completed"
        assert len(pooled.list_analyses(created["scenarioId"])) == 1

        profile = pooled.get_or_create_profile("pooled-profile")
        assert profile.profile_id == "pooled-profile"
        assert pooled.get_scenario(created["scenarioId"])["revisionNo"] == 2
    finally:
        pooled.close()


def test_live_pool_keeps_connections_bounded(pg_store):
    from poker_coach.persistence import PooledPostgresStore

    pooled = PooledPostgresStore(PG_URL, min_size=1, max_size=3)
    try:
        for index in range(20):
            pooled.get_or_create_profile(f"pooled-{index}")
        stats = pooled._pool.get_stats()
        assert stats.get("connections_num", 0) <= 3
        assert pooled.get_profile("pooled-7").profile_id == "pooled-7"
    finally:
        pooled.close()


def test_live_alembic_migration_upgrade_and_downgrade(pg_store):
    """Alembic must create and drop the full schema on a live database."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", PG_URL)

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    import psycopg

    with psycopg.connect(PG_URL, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT version_num FROM alembic_version")
            version = cursor.fetchone()[0]
    assert {
        "scenarios",
        "analysis_runs",
        "learning_profiles",
        "hand_events",
        "projection_checkpoints",
        "projection_snapshots",
        "outbox_messages",
    } <= tables
    assert version == "0003"

    # The migrated schema must satisfy the store contract.
    store = PostgresStore(PG_URL)
    try:
        created = store.create_scenario(scenario_at_flop(), title="migrated")
        assert store.get_scenario(created["scenarioId"])["revisionNo"] == 1
    finally:
        store.close()

    command.downgrade(config, "base")
    with psycopg.connect(PG_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
            )
            remaining = cursor.fetchone()[0]
    assert remaining == 1  # only alembic_version survives downgrade


def test_live_api_flow_over_postgres(pg_store):
    app = create_app(config=AppConfig(), store=pg_store)
    client = TestClient(app)

    response = client.post("/v1/scenarios/validate", json=scenario_at_flop().to_dict())
    assert response.status_code == 200
    assert response.json()["valid"] is True

    response = client.post(
        "/v1/scenarios",
        json={
            "scenario": scenario_at_flop().to_dict(),
            "title": "live regression spot",
            "tags": ["live"],
        },
    )
    assert response.status_code == 200
    scenario_id = response.json()["scenario"]["scenarioId"]

    response = client.post(f"/v1/scenarios/{scenario_id}/analyze")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["evidence"]["items"]
    assert response.json()["analysisRun"]["analysisId"]

    response = client.post(f"/v1/scenarios/{scenario_id}/teach", json={"depth": "beginner"})
    assert response.status_code == 200
    assert response.json()["response"]["summary"]["text"]

    response = client.post(f"/v1/scenarios/{scenario_id}/revisions/1/analyze")
    assert response.status_code == 200
    assert response.json()["revisionNo"] == 1
    assert response.json()["analysisRun"]["analysisId"]

    response = client.get(f"/v1/scenarios/{scenario_id}/analyses")
    assert response.status_code == 200
    assert len(response.json()["analyses"]) >= 2

    # The HTTP flow must have persisted through the live store.
    persisted = pg_store.get_scenario(scenario_id)
    assert persisted["revisionNo"] == 1
