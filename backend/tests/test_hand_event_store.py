"""Public contract tests for durable HandEventV1 append/read ports."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from poker_coach.persistence import SQLiteHandEventStore
from poker_coach.simulator import (
    ExpectedSequenceConflict,
    HandEventBatchError,
    HandEventIdentityConflict,
    RawHandEventV1,
)


def _raw_event(
    *,
    event_id: str = "evt-001",
    hand_id: str = "session-alpha:hand:1",
    sequence: int = 1,
) -> str:
    envelope = {
        "payload": {
            "rngSeed": 20260812,
            "startingStacks": {str(seat): 10_000 for seat in range(6)},
            "rakeBps": 0,
            "ante": 0,
            "bigBlind": 100,
            "smallBlind": 50,
            "buttonSeat": 0,
            "tableSize": 6,
            "ruleset": "nlhe",
            "kind": "hand_started",
        },
        "provenance": {
            "correlationId": "session-alpha",
            "producerVersion": "1.0.0",
            "producer": "riverline-tests",
        },
        "source": "fixture",
        "timestamp": "2026-08-12T00:00:01Z",
        "sequence": sequence,
        "handId": hand_id,
        "eventId": event_id,
        "schemaVersion": 1,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2)


def test_sqlite_append_survives_reopen_and_round_trips_original_event_json(tmp_path):
    path = tmp_path / "hand-events.sqlite3"
    raw_json = _raw_event()
    event = RawHandEventV1.from_json(raw_json)

    writer = SQLiteHandEventStore(path)
    result = writer.append(
        hand_id=event.event.hand_id,
        expected_sequence=0,
        events=(event,),
    )
    writer.close()

    reader = SQLiteHandEventStore(path)
    stored = reader.read(event.event.hand_id)
    reader.close()

    assert result.previous_sequence == 0
    assert result.last_sequence == 1
    assert result.appended_count == 1
    assert len(stored) == 1
    assert stored[0].raw_json == raw_json
    assert stored[0].event.source.value == "fixture"
    assert stored[0].event.provenance.correlation_id == "session-alpha"
    assert stored[0].event.payload.kind == "hand_started"


def test_raw_event_rejects_a_parsed_envelope_that_disagrees_with_its_json():
    original = RawHandEventV1.from_json(_raw_event())
    different_json = _raw_event(event_id="evt-different")

    with pytest.raises(ValueError, match="must describe the same HandEventV1"):
        RawHandEventV1(event=original.event, raw_json=different_json)


def test_sqlite_global_event_id_conflict_is_domain_error_and_rolls_back_batch(tmp_path):
    store = SQLiteHandEventStore(tmp_path / "identity-conflict.sqlite3")
    store.append(
        hand_id="hand-one",
        expected_sequence=0,
        events=(RawHandEventV1.from_json(_raw_event(hand_id="hand-one")),),
    )

    with pytest.raises(HandEventIdentityConflict) as caught:
        store.append(
            hand_id="hand-two",
            expected_sequence=0,
            events=(
                RawHandEventV1.from_json(
                    _raw_event(event_id="evt-unique", hand_id="hand-two")
                ),
                RawHandEventV1.from_json(
                    _raw_event(event_id="evt-001", hand_id="hand-two", sequence=2)
                ),
            ),
        )

    assert caught.value.code == "event_id_conflict"
    assert store.read("hand-two") == ()
    assert [item.event.event_id for item in store.read("hand-one")] == ["evt-001"]
    store.close()


@pytest.mark.parametrize(
    ("events", "error_code"),
    [
        (
            (
                RawHandEventV1.from_json(_raw_event(event_id="evt-2", sequence=2)),
                RawHandEventV1.from_json(_raw_event(event_id="evt-1", sequence=1)),
            ),
            "non_contiguous_batch",
        ),
        (
            (
                RawHandEventV1.from_json(_raw_event(event_id="evt-1", sequence=1)),
                RawHandEventV1.from_json(_raw_event(event_id="evt-3", sequence=3)),
            ),
            "non_contiguous_batch",
        ),
        (
            (
                RawHandEventV1.from_json(_raw_event(event_id="evt-1", sequence=1)),
                RawHandEventV1.from_json(_raw_event(event_id="evt-2", sequence=1)),
            ),
            "non_contiguous_batch",
        ),
        (
            (
                RawHandEventV1.from_json(_raw_event(event_id="evt-1", sequence=1)),
                RawHandEventV1.from_json(
                    _raw_event(event_id="evt-2", hand_id="another-hand", sequence=2)
                ),
            ),
            "cross_hand_batch",
        ),
        (
            (
                RawHandEventV1.from_json(_raw_event(event_id="evt-same", sequence=1)),
                RawHandEventV1.from_json(_raw_event(event_id="evt-same", sequence=2)),
            ),
            "duplicate_event_id_in_batch",
        ),
    ],
    ids=("out-of-order", "gap", "duplicate-sequence", "cross-hand", "duplicate-id"),
)
def test_sqlite_rejects_invalid_batch_atomically(tmp_path, events, error_code):
    store = SQLiteHandEventStore(tmp_path / f"{error_code}.sqlite3")

    with pytest.raises(HandEventBatchError) as caught:
        store.append(
            hand_id="session-alpha:hand:1",
            expected_sequence=0,
            events=events,
        )

    assert caught.value.code == error_code
    assert store.read("session-alpha:hand:1") == ()
    assert store.read("another-hand") == ()
    store.close()


def test_sqlite_stale_expected_sequence_fails_without_appending(tmp_path):
    store = SQLiteHandEventStore(tmp_path / "stale-sequence.sqlite3")
    hand_id = "session-alpha:hand:1"
    store.append(
        hand_id=hand_id,
        expected_sequence=0,
        events=(RawHandEventV1.from_json(_raw_event()),),
    )

    with pytest.raises(ExpectedSequenceConflict) as caught:
        store.append(
            hand_id=hand_id,
            expected_sequence=0,
            events=(RawHandEventV1.from_json(_raw_event(event_id="evt-stale")),),
        )

    assert caught.value.code == "expected_sequence_conflict"
    assert caught.value.expected_sequence == 0
    assert caught.value.actual_sequence == 1
    assert [item.event.event_id for item in store.read(hand_id)] == ["evt-001"]
    store.close()


def test_sqlite_two_writers_with_same_expected_sequence_only_one_succeeds(tmp_path):
    path = tmp_path / "writer-race.sqlite3"
    first = SQLiteHandEventStore(path)
    second = SQLiteHandEventStore(path)
    barrier = Barrier(2)

    def append(store, event_id):
        barrier.wait()
        try:
            return store.append(
                hand_id="session-alpha:hand:1",
                expected_sequence=0,
                events=(RawHandEventV1.from_json(_raw_event(event_id=event_id)),),
            )
        except ExpectedSequenceConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(append, (first, second), ("evt-writer-1", "evt-writer-2"))
        )

    assert sum(not isinstance(item, ExpectedSequenceConflict) for item in outcomes) == 1
    assert sum(isinstance(item, ExpectedSequenceConflict) for item in outcomes) == 1
    assert len(first.read("session-alpha:hand:1")) == 1
    first.close()
    second.close()
