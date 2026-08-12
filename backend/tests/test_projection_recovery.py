"""Recovery contract tests over the durable HandEventV1 stream."""

from __future__ import annotations

import json
import sqlite3

import pytest

from poker_coach.persistence import SQLiteHandEventStore, SQLiteProjectionStore
from poker_coach.simulator import (
    ProjectionIdentityV1,
    ProjectionRunner,
    ProjectionStoreFailure,
    RawHandEventV1,
    UnsupportedRecoverySchemaVersion,
)


def _raw_event(*, event_id: str, sequence: int) -> RawHandEventV1:
    payload: dict[str, object]
    if sequence == 1:
        payload = {
            "kind": "hand_started",
            "ruleset": "nlhe",
            "tableSize": 2,
            "buttonSeat": 0,
            "smallBlind": 50,
            "bigBlind": 100,
            "startingStacks": {"0": 10_000, "1": 10_000},
            "rngSeed": 20260812,
        }
    else:
        payload = {
            "kind": "hole_cards_recorded",
            "seatId": sequence - 2,
            "cards": ["As", "Kd"] if sequence == 2 else ["Qc", "Jh"],
        }
    return RawHandEventV1.from_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "eventId": event_id,
                "handId": "session-recovery:hand:1",
                "sequence": sequence,
                "timestamp": f"2026-08-12T00:00:0{sequence}Z",
                "source": "fixture",
                "provenance": {
                    "producer": "riverline-tests",
                    "producerVersion": "1.0.0",
                    "correlationId": "session-recovery",
                },
                "payload": payload,
            }
        )
    )


def test_projection_identity_is_versioned_frozen_and_uses_camel_case_json():
    identity = ProjectionIdentityV1(
        projection_name="hand_summary",
        projection_version=2,
    )

    assert json.loads(identity.to_json()) == {
        "projectionName": "hand_summary",
        "projectionVersion": 2,
        "schemaVersion": 1,
    }
    with pytest.raises(Exception):
        identity.projection_version = 3


def test_failed_projector_restarts_from_durable_cursor_without_skipping_or_reapplying(
    tmp_path,
):
    path = tmp_path / "projection-recovery.sqlite3"
    events = tuple(
        _raw_event(event_id=f"evt-{sequence}", sequence=sequence)
        for sequence in range(1, 4)
    )
    event_store = SQLiteHandEventStore(path)
    event_store.append(
        hand_id=events[0].event.hand_id,
        expected_sequence=0,
        events=events,
    )
    projection_store = SQLiteProjectionStore(path)
    identity = ProjectionIdentityV1(
        projection_name="event_ids",
        projection_version=1,
    )
    failed_once = False

    def flaky_projector(snapshot, event):
        nonlocal failed_once
        if event.sequence == 2 and not failed_once:
            failed_once = True
            raise RuntimeError("simulated projector failure")
        return {"eventIds": [*(snapshot or {}).get("eventIds", []), event.event_id]}

    runner = ProjectionRunner(event_store, projection_store, identity, flaky_projector)
    with pytest.raises(RuntimeError, match="simulated projector failure"):
        runner.run(events[0].event.hand_id)

    failed_checkpoint = projection_store.load_checkpoint(
        identity, events[0].event.hand_id
    )
    assert failed_checkpoint.last_sequence == 1
    assert projection_store.load_snapshot(identity, events[0].event.hand_id).payload == {
        "eventIds": ["evt-1"]
    }
    projection_store.close()
    event_store.close()

    restarted_events = SQLiteHandEventStore(path)
    restarted_projections = SQLiteProjectionStore(path)
    restarted_runner = ProjectionRunner(
        restarted_events,
        restarted_projections,
        identity,
        flaky_projector,
    )
    completed = restarted_runner.run(events[0].event.hand_id)
    duplicate = restarted_runner.run(events[0].event.hand_id)

    assert completed.payload == {"eventIds": ["evt-1", "evt-2", "evt-3"]}
    assert duplicate.payload == completed.payload
    assert duplicate.fingerprint == completed.fingerprint
    assert restarted_projections.load_checkpoint(
        identity, events[0].event.hand_id
    ).last_sequence == 3
    restarted_projections.close()
    restarted_events.close()


def test_discarded_snapshot_rebuilds_to_the_same_read_model_and_fingerprint(tmp_path):
    path = tmp_path / "projection-rebuild.sqlite3"
    events = tuple(
        _raw_event(event_id=f"evt-rebuild-{sequence}", sequence=sequence)
        for sequence in range(1, 4)
    )
    event_store = SQLiteHandEventStore(path)
    event_store.append(
        hand_id=events[0].event.hand_id,
        expected_sequence=0,
        events=events,
    )
    projection_store = SQLiteProjectionStore(path)
    identity = ProjectionIdentityV1(
        projection_name="event_kinds",
        projection_version=1,
    )

    def projector(snapshot, event):
        return {"kinds": [*(snapshot or {}).get("kinds", []), event.payload.kind]}

    runner = ProjectionRunner(event_store, projection_store, identity, projector)
    incremental = runner.run(events[0].event.hand_id)
    projection_store.discard(identity, events[0].event.hand_id)

    assert projection_store.load_snapshot(identity, events[0].event.hand_id) is None
    assert projection_store.load_checkpoint(
        identity, events[0].event.hand_id
    ).last_sequence == 0

    rebuilt = runner.run(events[0].event.hand_id)
    assert rebuilt.payload == incremental.payload
    assert rebuilt.fingerprint == incremental.fingerprint
    assert [raw.raw_json for raw in event_store.read(events[0].event.hand_id)] == [
        raw.raw_json for raw in events
    ]
    projection_store.close()
    event_store.close()


def test_snapshot_database_failure_rolls_back_without_advancing_checkpoint(tmp_path):
    path = tmp_path / "projection-write-failure.sqlite3"
    identity = ProjectionIdentityV1(
        projection_name="fault_injected",
        projection_version=1,
    )
    first = _raw_event(event_id="evt-fault-1", sequence=1).event
    second = _raw_event(event_id="evt-fault-2", sequence=2).event
    store = SQLiteProjectionStore(path)
    before = store.apply(
        identity,
        first.hand_id,
        expected_sequence=0,
        event=first,
        payload={"eventIds": [first.event_id]},
    )
    with sqlite3.connect(path) as fault_connection:
        fault_connection.execute(
            """
            CREATE TRIGGER fail_projection_snapshot_update
            BEFORE UPDATE ON projection_snapshots
            WHEN NEW.sequence = 2
            BEGIN
                SELECT RAISE(ABORT, 'simulated snapshot write failure');
            END
            """
        )

    with pytest.raises(ProjectionStoreFailure) as caught:
        store.apply(
            identity,
            second.hand_id,
            expected_sequence=1,
            event=second,
            payload={"eventIds": [first.event_id, second.event_id]},
        )

    assert caught.value.code == "storage_failure"
    assert store.load_snapshot(identity, first.hand_id) == before
    checkpoint = store.load_checkpoint(identity, first.hand_id)
    assert checkpoint.last_sequence == 1
    assert checkpoint.last_event_id == first.event_id
    store.close()


def test_sqlite_snapshot_reader_rejects_unknown_persisted_schema_version(tmp_path):
    path = tmp_path / "snapshot-unknown-schema.sqlite3"
    identity = ProjectionIdentityV1(
        projection_name="unknown_schema",
        projection_version=1,
    )
    event = _raw_event(event_id="evt-snapshot-schema", sequence=1).event
    store = SQLiteProjectionStore(path)
    store.apply(
        identity,
        event.hand_id,
        expected_sequence=0,
        event=event,
        payload={"eventIds": [event.event_id]},
    )
    with sqlite3.connect(path) as future_writer:
        future_writer.execute(
            "UPDATE projection_snapshots SET schema_version = 2 "
            "WHERE projection_name = ? AND projection_version = ? AND stream_id = ?",
            (identity.projection_name, identity.projection_version, event.hand_id),
        )

    with pytest.raises(UnsupportedRecoverySchemaVersion) as caught:
        store.load_snapshot(identity, event.hand_id)

    assert caught.value.code == "unsupported_recovery_schema_version"
    assert "driver" not in str(caught.value).lower()
    store.close()
