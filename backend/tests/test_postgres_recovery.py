"""PostgreSQL projection/outbox SQL and adapter contract evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poker_coach.persistence import PostgresHandEventStore, PostgresProjectionStore
from poker_coach.simulator import (
    OutboxIdentityConflict,
    OutboxBindingError,
    OutboxClaimError,
    OutboxIntentV1,
    ProjectionIdentityV1,
    RawHandEventV1,
    UnsupportedRecoverySchemaVersion,
)


def _event() -> RawHandEventV1:
    return RawHandEventV1.from_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "eventId": "evt-pg-outbox",
                "handId": "hand-pg-outbox",
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
    )


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

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


class ClaimCursor(FakeCursor):
    rowcount = 1

    def __init__(self, connection):
        super().__init__(connection)
        self.last_query = ""

    def execute(self, query, params=()):
        self.last_query = query
        super().execute(query, params)

    def fetchall(self):
        if "SELECT message_id FROM outbox_messages" in self.last_query:
            return [("msg-pg-claim",)]
        return []

    def fetchone(self):
        if "RETURNING message_id" in self.last_query:
            return (
                "msg-pg-claim",
                "evt-pg-outbox",
                "evt-pg-outbox:review_requested",
                1,
                "hand.review.requested",
                '{"handId":"hand-pg-outbox"}',
                "processing",
                2,
                "1970-01-01T00:00:00+00:00",
                "worker-pg",
                "2026-08-12T00:00:30+00:00",
                "claim-token-pg",
                None,
            )
        return (0,)


class ClaimConnection(FakeConnection):
    def cursor(self):
        return ClaimCursor(self)


class _OutboxDiagnostic:
    constraint_name = "uq_outbox_messages_idempotency_key"


class OutboxUniqueViolation(Exception):
    sqlstate = "23505"
    diag = _OutboxDiagnostic()


class OutboxFailingCursor(FakeCursor):
    def execute(self, query, params=()):
        super().execute(query, params)
        if "INSERT INTO outbox_messages" in query:
            raise OutboxUniqueViolation("driver detail must not escape")


class OutboxFailingConnection(FakeConnection):
    def cursor(self):
        return OutboxFailingCursor(self)


class TokenCursor(FakeCursor):
    def __init__(self, connection):
        super().__init__(connection)
        self.rowcount = 0

    def execute(self, query, params=()):
        super().execute(query, params)
        if "claim_token = %s" in query:
            self.rowcount = 1 if params[-2] == "new-token" else 0


class TokenConnection(FakeConnection):
    def cursor(self):
        return TokenCursor(self)


class FutureOutboxCursor(FakeCursor):
    def __init__(self, connection):
        super().__init__(connection)
        self.last_query = ""

    def execute(self, query, params=()):
        self.last_query = query
        super().execute(query, params)

    def fetchone(self):
        if "FROM outbox_messages" in self.last_query:
            return (
                "msg-future",
                "evt-future",
                "evt-future:review_requested",
                2,
                "hand.review.requested",
                '{"handId":"hand-future"}',
                "pending",
                0,
                "1970-01-01T00:00:00+00:00",
                None,
                None,
                None,
                None,
            )
        return (0,)


class FutureOutboxConnection(FakeConnection):
    def cursor(self):
        return FutureOutboxCursor(self)


class FutureSnapshotCursor(FakeCursor):
    def __init__(self, connection):
        super().__init__(connection)
        self.last_query = ""

    def execute(self, query, params=()):
        self.last_query = query
        super().execute(query, params)

    def fetchone(self):
        if "FROM projection_snapshots" in self.last_query:
            return (1, "evt-future", 2, '{"eventIds":["evt-future"]}', "0" * 64)
        return (0,)


class FutureSnapshotConnection(FakeConnection):
    def cursor(self):
        return FutureSnapshotCursor(self)


def test_alembic_0003_adds_projection_checkpoint_snapshot_and_outbox_tables():
    backend = Path(__file__).resolve().parents[1]
    migration = (backend / "migrations" / "versions" / "0003_recovery.py").read_text(
        encoding="utf-8"
    )
    projection_schema = (
        backend / "poker_coach" / "persistence" / "projection_schema.sql"
    ).read_text(encoding="utf-8")
    outbox_schema = (
        backend / "poker_coach" / "persistence" / "outbox_schema.sql"
    ).read_text(encoding="utf-8")

    assert 'revision = "0003"' in migration
    assert 'down_revision = "0002"' in migration
    assert "pk_projection_checkpoints" in projection_schema
    assert "pk_projection_snapshots" in projection_schema
    assert "pk_outbox_messages" in outbox_schema
    assert "uq_outbox_messages_idempotency_key" in outbox_schema
    assert "source_event_id TEXT NOT NULL" in outbox_schema
    assert "fk_outbox_messages_source_event" in outbox_schema
    assert "claim_token TEXT" in outbox_schema


def test_postgres_event_and_outbox_intent_share_one_append_transaction():
    connection = FakeConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)
    event = _event()
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )

    store.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
        outbox_intents=(intent,),
    )

    queries = [query for query, _ in connection.statements]
    event_insert = next(
        index for index, query in enumerate(queries) if "INSERT INTO hand_events" in query
    )
    outbox_insert = next(
        index
        for index, query in enumerate(queries)
        if "INSERT INTO outbox_messages" in query
    )
    assert event_insert < outbox_insert
    assert connection.commits == 2  # schema initialization plus one atomic append
    assert connection.rollbacks == 0


def test_postgres_projection_writes_snapshot_before_checkpoint_in_one_transaction():
    connection = FakeConnection()
    store = PostgresProjectionStore("postgresql://test", connection=connection)
    event = _event().event
    identity = ProjectionIdentityV1(
        projection_name="hand_summary",
        projection_version=1,
    )

    snapshot = store.apply(
        identity,
        event.hand_id,
        expected_sequence=0,
        event=event,
        payload={"eventIds": [event.event_id]},
    )

    queries = [query for query, _ in connection.statements]
    snapshot_insert = next(
        index
        for index, query in enumerate(queries)
        if "INSERT INTO projection_snapshots" in query
    )
    checkpoint_insert = next(
        index
        for index, query in enumerate(queries)
        if "INSERT INTO projection_checkpoints" in query
    )
    assert snapshot_insert < checkpoint_insert
    assert snapshot.sequence == 1
    assert connection.commits == 2  # schema initialization plus one atomic apply
    assert connection.rollbacks == 0


def test_postgres_claim_recovers_expired_leases_and_locks_rows_without_blocking():
    connection = ClaimConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)

    claimed = store.claim_outbox(
        worker_id="worker-pg",
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        lease_seconds=30,
        limit=10,
    )

    queries = [query for query, _ in connection.statements]
    recovery_index = next(
        index
        for index, query in enumerate(queries)
        if "lease_expires_at <= %s" in query
    )
    claim_index = next(
        index for index, query in enumerate(queries) if "FOR UPDATE SKIP LOCKED" in query
    )
    assert recovery_index < claim_index
    assert len(claimed) == 1
    assert claimed[0].claimed_by == "worker-pg"
    assert claimed[0].attempt_count == 2
    assert claimed[0].source_event_id == "evt-pg-outbox"
    assert claimed[0].claim_token == "claim-token-pg"
    assert connection.commits == 2  # schema initialization plus one claim transaction
    assert connection.rollbacks == 0


def test_postgres_outbox_conflict_rolls_back_the_event_append_transaction():
    connection = OutboxFailingConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)
    event = _event()
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )

    with pytest.raises(OutboxIdentityConflict) as caught:
        store.append(
            hand_id=event.event.hand_id,
            expected_sequence=0,
            events=(event,),
            outbox_intents=(intent,),
        )

    assert caught.value.code == "outbox_identity_conflict"
    assert "driver detail" not in str(caught.value)
    assert connection.commits == 1  # initialization only
    assert connection.rollbacks == 1


def test_postgres_append_rejects_outbox_source_outside_the_same_batch():
    connection = FakeConnection()
    store = PostgresHandEventStore("postgresql://test", connection=connection)
    event = _event()
    orphan = OutboxIntentV1.for_event(
        event_id="evt-not-in-batch",
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )

    with pytest.raises(OutboxBindingError) as caught:
        store.append(
            hand_id=event.event.hand_id,
            expected_sequence=0,
            events=(event,),
            outbox_intents=(orphan,),
        )

    assert caught.value.code == "outbox_source_not_in_batch"
    assert connection.commits == 1  # initialization only; append transaction never opens
    assert connection.rollbacks == 0


def test_postgres_ack_and_retry_require_current_claim_token_and_store_time():
    connection = TokenConnection()
    current_time = datetime(2026, 8, 12, 0, 0, 5, tzinfo=timezone.utc)
    store = PostgresHandEventStore(
        "postgresql://test", connection=connection, clock=lambda: current_time
    )

    with pytest.raises(OutboxClaimError):
        store.mark_outbox_dispatched(
            message_id="msg-token",
            worker_id="reused-worker",
            claim_token="old-token",
        )
    with pytest.raises(OutboxClaimError):
        store.retry_outbox(
            message_id="msg-token",
            worker_id="reused-worker",
            claim_token="old-token",
            retry_delay_seconds=0,
            error="stale retry",
        )
    store.mark_outbox_dispatched(
        message_id="msg-token",
        worker_id="reused-worker",
        claim_token="new-token",
    )

    token_updates = [
        (query, params)
        for query, params in connection.statements
        if "claim_token = %s" in query
    ]
    assert [params[-2] for _, params in token_updates] == [
        "old-token",
        "old-token",
        "new-token",
    ]
    expected_time = current_time.isoformat()
    assert all(params[-1] == expected_time for _, params in token_updates)
    retry_params = next(
        params for query, params in token_updates if "available_at = %s" in query
    )
    assert retry_params[0] == expected_time


def test_postgres_outbox_reader_rejects_unknown_persisted_schema_version():
    store = PostgresHandEventStore(
        "postgresql://test", connection=FutureOutboxConnection()
    )

    with pytest.raises(UnsupportedRecoverySchemaVersion) as caught:
        store.load_outbox("msg-future")

    assert caught.value.code == "unsupported_recovery_schema_version"
    assert "driver" not in str(caught.value).lower()


def test_postgres_snapshot_reader_rejects_unknown_persisted_schema_version():
    store = PostgresProjectionStore(
        "postgresql://test", connection=FutureSnapshotConnection()
    )
    identity = ProjectionIdentityV1(
        projection_name="future_snapshot",
        projection_version=1,
    )

    with pytest.raises(UnsupportedRecoverySchemaVersion) as caught:
        store.load_snapshot(identity, "hand-future")

    assert caught.value.code == "unsupported_recovery_schema_version"
    assert "driver" not in str(caught.value).lower()
