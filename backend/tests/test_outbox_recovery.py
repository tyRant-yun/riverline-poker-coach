"""Transactional outbox recovery and idempotent dispatch contract tests."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from poker_coach.persistence import SQLiteHandEventStore
from poker_coach.simulator import (
    HandEventIdentityConflict,
    OutboxBindingError,
    OutboxClaimError,
    OutboxDispatcher,
    OutboxIdentityConflict,
    OutboxIntentV1,
    OutboxStatusV1,
    RawHandEventV1,
    UnsupportedRecoverySchemaVersion,
)


def _event(*, event_id: str, hand_id: str, sequence: int = 1) -> RawHandEventV1:
    return RawHandEventV1.from_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "eventId": event_id,
                "handId": hand_id,
                "sequence": sequence,
                "timestamp": "2026-08-12T00:00:01Z",
                "source": "fixture",
                "provenance": {
                    "producer": "riverline-tests",
                    "producerVersion": "1.0.0",
                    "correlationId": "session-outbox",
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


def test_outbox_intent_has_deterministic_identity_and_versioned_camel_case_json():
    first = OutboxIntentV1.for_event(
        event_id="evt-001",
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": "session-alpha:hand:1"},
    )
    retry = OutboxIntentV1.for_event(
        event_id="evt-001",
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": "session-alpha:hand:1"},
    )

    assert retry == first
    assert first.idempotency_key == "evt-001:review_requested"
    assert first.source_event_id == "evt-001"
    assert json.loads(first.to_json()) == {
        "idempotencyKey": "evt-001:review_requested",
        "messageId": first.message_id,
        "payload": {"handId": "session-alpha:hand:1"},
        "schemaVersion": 1,
        "sourceEventId": "evt-001",
        "topic": "hand.review.requested",
    }


def test_sqlite_event_append_and_outbox_intent_are_atomic_and_survive_restart(tmp_path):
    path = tmp_path / "atomic-outbox.sqlite3"
    first_event = _event(event_id="evt-shared", hand_id="hand-one")
    first_intent = OutboxIntentV1.for_event(
        event_id=first_event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": first_event.event.hand_id},
    )
    store = SQLiteHandEventStore(path)
    store.append(
        hand_id=first_event.event.hand_id,
        expected_sequence=0,
        events=(first_event,),
        outbox_intents=(first_intent,),
    )
    store.close()

    restarted = SQLiteHandEventStore(path)
    claimed = restarted.claim_outbox(
        worker_id="worker-a",
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        lease_seconds=30,
    )
    assert [message.idempotency_key for message in claimed] == [
        "evt-shared:review_requested"
    ]
    restarted.close()

    rollback_path = tmp_path / "rollback-outbox.sqlite3"
    rollback_store = SQLiteHandEventStore(rollback_path)
    rollback_store.append(
        hand_id="hand-one",
        expected_sequence=0,
        events=(_event(event_id="evt-shared", hand_id="hand-one"),),
    )
    conflicting_intent = OutboxIntentV1.for_event(
        event_id="evt-unique",
        purpose="must_not_escape",
        topic="hand.review.requested",
        payload={"handId": "hand-two"},
    )
    with pytest.raises(HandEventIdentityConflict):
        rollback_store.append(
            hand_id="hand-two",
            expected_sequence=0,
            events=(
                _event(event_id="evt-unique", hand_id="hand-two"),
                _event(event_id="evt-shared", hand_id="hand-two", sequence=2),
            ),
            outbox_intents=(conflicting_intent,),
        )

    assert rollback_store.read("hand-two") == ()
    assert rollback_store.claim_outbox(
        worker_id="worker-a",
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        lease_seconds=30,
    ) == ()
    rollback_store.close()


def test_outbox_failure_retries_after_restart_without_duplicate_external_side_effect(
    tmp_path,
):
    path = tmp_path / "outbox-retry.sqlite3"
    event = _event(event_id="evt-retry", hand_id="hand-retry")
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )
    store = SQLiteHandEventStore(path)
    store.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
        outbox_intents=(intent,),
    )
    side_effects: set[str] = set()
    deliveries: list[str] = []
    lose_first_ack = True

    def idempotent_sink(message):
        nonlocal lose_first_ack
        deliveries.append(message.idempotency_key)
        side_effects.add(message.idempotency_key)
        if lose_first_ack:
            lose_first_ack = False
            raise RuntimeError("external effect committed but acknowledgement was lost")

    first = OutboxDispatcher(store).dispatch_once(
        worker_id="worker-a",
        dispatch=idempotent_sink,
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        retry_delay_seconds=0,
    )
    assert (first.claimed_count, first.dispatched_count, first.failed_count) == (1, 0, 1)
    assert store.load_outbox(intent.message_id).status is OutboxStatusV1.PENDING
    store.close()

    restarted = SQLiteHandEventStore(path)
    dispatcher = OutboxDispatcher(restarted)
    second = dispatcher.dispatch_once(
        worker_id="worker-b",
        dispatch=idempotent_sink,
        now=datetime(2026, 8, 12, 0, 0, 1, tzinfo=timezone.utc),
        retry_delay_seconds=0,
    )
    empty = dispatcher.dispatch_once(
        worker_id="worker-b",
        dispatch=idempotent_sink,
        now=datetime(2026, 8, 12, 0, 0, 2, tzinfo=timezone.utc),
        retry_delay_seconds=0,
    )

    assert (second.claimed_count, second.dispatched_count, second.failed_count) == (1, 1, 0)
    assert empty.claimed_count == 0
    assert deliveries == [intent.idempotency_key, intent.idempotency_key]
    assert side_effects == {intent.idempotency_key}
    final = restarted.load_outbox(intent.message_id)
    assert final.status is OutboxStatusV1.DISPATCHED
    assert final.attempt_count == 2
    restarted.close()


def test_concurrent_claim_has_one_owner_and_expired_processing_lease_recovers(tmp_path):
    path = tmp_path / "outbox-claim-race.sqlite3"
    event = _event(event_id="evt-claim", hand_id="hand-claim")
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )
    first = SQLiteHandEventStore(path)
    first.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
        outbox_intents=(intent,),
    )
    second = SQLiteHandEventStore(path)
    barrier = Barrier(2)
    claim_time = datetime(2026, 8, 12, tzinfo=timezone.utc)

    def claim(store, worker_id):
        barrier.wait()
        return store.claim_outbox(
            worker_id=worker_id,
            now=claim_time,
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(claim, (first, second), ("worker-a", "worker-b")))

    assert sorted(len(batch) for batch in claims) == [0, 1]
    owner_message = next(batch[0] for batch in claims if batch)
    assert owner_message.status is OutboxStatusV1.PROCESSING
    assert owner_message.attempt_count == 1
    first.close()
    second.close()

    restarted = SQLiteHandEventStore(path)
    recovered = restarted.claim_outbox(
        worker_id="worker-recovery",
        now=datetime(2026, 8, 12, 0, 0, 31, tzinfo=timezone.utc),
        lease_seconds=30,
    )
    assert len(recovered) == 1
    assert recovered[0].claimed_by == "worker-recovery"
    assert recovered[0].attempt_count == 2
    restarted.close()


def test_outbox_identity_conflict_rolls_back_event_rows_from_the_same_append(tmp_path):
    path = tmp_path / "outbox-conflict-rollback.sqlite3"
    store = SQLiteHandEventStore(path)
    first_event = _event(event_id="evt-first", hand_id="hand-first")
    durable_intent = OutboxIntentV1.for_event(
        event_id=first_event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": "hand-first"},
    )
    store.append(
        hand_id=first_event.event.hand_id,
        expected_sequence=0,
        events=(first_event,),
        outbox_intents=(durable_intent,),
    )
    second_event = _event(event_id="evt-second", hand_id="hand-second")
    conflicting_intent = OutboxIntentV1(
        message_id=durable_intent.message_id,
        source_event_id=second_event.event.event_id,
        idempotency_key=durable_intent.idempotency_key,
        topic=durable_intent.topic,
        payload={"handId": second_event.event.hand_id},
    )

    with pytest.raises(OutboxIdentityConflict):
        store.append(
            hand_id=second_event.event.hand_id,
            expected_sequence=0,
            events=(second_event,),
            outbox_intents=(conflicting_intent,),
        )

    assert store.read(second_event.event.hand_id) == ()
    assert store.read(first_event.event.hand_id) == (first_event,)
    store.close()


@pytest.mark.parametrize(
    "source_event_id",
    ("evt-missing", "evt-other-hand", "evt-prior-append"),
    ids=("missing", "other-hand", "prior-append"),
)
def test_outbox_intent_must_bind_to_an_event_in_the_same_append_batch(
    tmp_path, source_event_id
):
    store = SQLiteHandEventStore(tmp_path / f"binding-{source_event_id}.sqlite3")
    target_hand = "hand-binding-target"
    prior = _event(event_id="evt-prior-append", hand_id=target_hand)
    other = _event(event_id="evt-other-hand", hand_id="hand-binding-other")
    store.append(hand_id=target_hand, expected_sequence=0, events=(prior,))
    store.append(hand_id=other.event.hand_id, expected_sequence=0, events=(other,))
    current = _event(event_id="evt-current", hand_id=target_hand, sequence=2)
    orphan = OutboxIntentV1.for_event(
        event_id=source_event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": target_hand},
    )

    with pytest.raises(OutboxBindingError) as caught:
        store.append(
            hand_id=target_hand,
            expected_sequence=1,
            events=(current,),
            outbox_intents=(orphan,),
        )

    assert caught.value.code == "outbox_source_not_in_batch"
    assert store.read(target_hand) == (prior,)
    assert store.read(other.event.hand_id) == (other,)
    store.close()


def test_expired_claim_token_cannot_ack_or_retry_a_new_claim_with_same_worker_id(
    tmp_path,
):
    path = tmp_path / "outbox-claim-token.sqlite3"
    event = _event(event_id="evt-claim-token", hand_id="hand-claim-token")
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )
    store = SQLiteHandEventStore(path)
    store.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
        outbox_intents=(intent,),
    )
    old_claim = store.claim_outbox(
        worker_id="reused-worker",
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        lease_seconds=1,
    )[0]
    expired_at = datetime(2026, 8, 12, 0, 0, 2, tzinfo=timezone.utc)
    with pytest.raises(OutboxClaimError) as expired_error:
        store.mark_outbox_dispatched(
            message_id=intent.message_id,
            worker_id="reused-worker",
            claim_token=old_claim.claim_token,
            now=expired_at,
        )
    assert expired_error.value.code == "outbox_claim_lost"
    new_claim = store.claim_outbox(
        worker_id="reused-worker",
        now=expired_at,
        lease_seconds=30,
    )[0]

    assert old_claim.claim_token
    assert new_claim.claim_token
    assert old_claim.claim_token != new_claim.claim_token
    with pytest.raises(OutboxClaimError) as ack_error:
        store.mark_outbox_dispatched(
            message_id=intent.message_id,
            worker_id="reused-worker",
            claim_token=old_claim.claim_token,
            now=expired_at,
        )
    with pytest.raises(OutboxClaimError) as retry_error:
        store.retry_outbox(
            message_id=intent.message_id,
            worker_id="reused-worker",
            claim_token=old_claim.claim_token,
            now=datetime(2026, 8, 12, 0, 0, 3, tzinfo=timezone.utc),
            available_at=datetime(2026, 8, 12, 0, 0, 3, tzinfo=timezone.utc),
            error="stale retry",
        )

    assert ack_error.value.code == "outbox_claim_lost"
    assert retry_error.value.code == "outbox_claim_lost"
    still_owned = store.load_outbox(intent.message_id)
    assert still_owned.status is OutboxStatusV1.PROCESSING
    assert still_owned.claim_token == new_claim.claim_token
    store.mark_outbox_dispatched(
        message_id=intent.message_id,
        worker_id="reused-worker",
        claim_token=new_claim.claim_token,
        now=datetime(2026, 8, 12, 0, 0, 3, tzinfo=timezone.utc),
    )
    assert store.load_outbox(intent.message_id).status is OutboxStatusV1.DISPATCHED
    store.close()


def test_sqlite_outbox_reader_rejects_unknown_persisted_schema_version(tmp_path):
    path = tmp_path / "outbox-unknown-schema.sqlite3"
    event = _event(event_id="evt-unknown-schema", hand_id="hand-unknown-schema")
    intent = OutboxIntentV1.for_event(
        event_id=event.event.event_id,
        purpose="review_requested",
        topic="hand.review.requested",
        payload={"handId": event.event.hand_id},
    )
    store = SQLiteHandEventStore(path)
    store.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
        outbox_intents=(intent,),
    )
    with sqlite3.connect(path) as future_writer:
        future_writer.execute(
            "UPDATE outbox_messages SET schema_version = 2 WHERE message_id = ?",
            (intent.message_id,),
        )

    with pytest.raises(UnsupportedRecoverySchemaVersion) as caught:
        store.load_outbox(intent.message_id)

    assert caught.value.code == "unsupported_recovery_schema_version"
    assert "driver" not in str(caught.value).lower()
    store.close()
