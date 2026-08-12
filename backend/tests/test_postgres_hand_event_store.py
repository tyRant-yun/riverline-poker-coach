"""PostgreSQL HandEventStore contract and SQL evidence without a live server."""

from __future__ import annotations

from pathlib import Path

import pytest

from poker_coach.persistence import PostgresHandEventStore
from poker_coach.simulator import HandEventIdentityConflict, HandEventV1, RawHandEventV1


def _event() -> RawHandEventV1:
    event = HandEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": "evt-pg-001",
            "handId": "session-pg:hand:1",
            "sequence": 1,
            "timestamp": "2026-08-12T00:00:01Z",
            "source": "fixture",
            "provenance": {
                "producer": "riverline-tests",
                "producerVersion": "1.0.0",
                "correlationId": "session-pg",
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
    return RawHandEventV1.from_event(event)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []

    def execute(self, query, params=()):
        self.connection.statements.append((query, tuple(params)))

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        return None


class _Diagnostic:
    constraint_name = "pk_hand_events"


class FakeUniqueViolation(Exception):
    sqlstate = "23505"
    diag = _Diagnostic()


class FailingCursor(FakeCursor):
    def execute(self, query, params=()):
        super().execute(query, params)
        if "INSERT INTO hand_events" in query:
            raise FakeUniqueViolation("driver detail must not escape")


class FailingConnection(FakeConnection):
    def cursor(self):
        return FailingCursor(self)


def test_hand_events_schema_has_both_durable_uniqueness_constraints():
    schema = (
        Path(__file__).resolve().parents[1]
        / "poker_coach"
        / "persistence"
        / "hand_events_schema.sql"
    ).read_text(encoding="utf-8")

    assert "CONSTRAINT pk_hand_events PRIMARY KEY (event_id)" in schema
    assert "CONSTRAINT uq_hand_events_hand_sequence UNIQUE (hand_id, sequence)" in schema
    assert "raw_event_json TEXT NOT NULL" in schema
    assert "provenance_json TEXT NOT NULL" in schema
    assert "payload_json TEXT NOT NULL" in schema


def test_alembic_0002_adds_and_removes_only_the_hand_events_table():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0002_hand_events.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0002"' in migration
    assert 'down_revision = "0001"' in migration
    assert 'Path(__file__).resolve().parents[2]' in migration
    assert 'op.execute("DROP TABLE IF EXISTS hand_events")' in migration


def test_postgres_append_locks_hand_before_expected_sequence_check_and_insert():
    connection = FakeConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)
    event = _event()

    result = store.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
    )

    queries = [query for query, _ in connection.statements]
    lock_index = next(
        index for index, query in enumerate(queries) if "pg_advisory_xact_lock" in query
    )
    head_index = next(
        index for index, query in enumerate(queries) if "MAX(sequence)" in query
    )
    insert_index = next(
        index for index, query in enumerate(queries) if "INSERT INTO hand_events" in query
    )
    assert lock_index < head_index < insert_index
    assert result.last_sequence == 1
    assert connection.commits == 2  # schema initialization and atomic append
    assert connection.rollbacks == 0
    store.close()


def test_postgres_unique_violation_maps_to_stable_domain_error_and_rolls_back():
    connection = FailingConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)
    event = _event()

    with pytest.raises(HandEventIdentityConflict) as caught:
        store.append(
            hand_id=event.event.hand_id,
            expected_sequence=0,
            events=(event,),
        )

    assert caught.value.code == "event_id_conflict"
    assert "driver detail" not in str(caught.value)
    assert connection.rollbacks == 1
