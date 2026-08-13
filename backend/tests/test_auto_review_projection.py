"""Focused contract tests for terminal, event-backed automatic reviews."""

from __future__ import annotations

import json

import pytest

from poker_coach.persistence.hand_event_store import SQLiteHandEventStore
from poker_coach.persistence.review_projection_store import SQLiteReviewProjectionStore
from poker_coach.simulator.auto_review import (
    AutomaticReviewProjectionService,
    ReviewProjectionError,
)
from poker_coach.simulator.event_store import RawHandEventV1


def _event(*, sequence: int, payload: dict[str, object]) -> RawHandEventV1:
    return RawHandEventV1.from_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "eventId": f"review-event-{sequence}",
                "handId": "review-session:hand:1",
                "sequence": sequence,
                "timestamp": f"2026-08-13T00:00:{sequence:02d}Z",
                "source": "fixture",
                "provenance": {
                    "producer": "auto-review-tests",
                    "producerVersion": "1.0.0",
                    "correlationId": "review-session",
                },
                "payload": payload,
            }
        )
    )


def _stream(*, terminal: bool = True) -> tuple[RawHandEventV1, ...]:
    events = [
        _event(
            sequence=1,
            payload={
                "kind": "hand_started",
                "ruleset": "nlhe",
                "tableSize": 2,
                "buttonSeat": 0,
                "smallBlind": 50,
                "bigBlind": 100,
                "startingStacks": {"0": 10_000, "1": 10_000},
                "activeSeatIds": [0, 1],
                "rngSeed": 20260813,
            },
        ),
        _event(
            sequence=2,
            payload={
                "kind": "action_taken",
                "street": "preflop",
                "actorSeat": 0,
                "action": "raise",
                "amount": 300,
                "amountSemantics": "to",
            },
        ),
        _event(
            sequence=3,
            payload={
                "kind": "action_taken",
                "street": "preflop",
                "actorSeat": 1,
                "action": "fold",
                "amountSemantics": "none",
            },
        ),
    ]
    if terminal:
        events.append(
            _event(
                sequence=4,
                payload={
                    "kind": "hand_completed",
                    "winnerSeats": [0],
                    "payouts": {"0": 150},
                },
            )
        )
    return tuple(events)


def _append(store: SQLiteHandEventStore, stream: tuple[RawHandEventV1, ...]) -> None:
    store.append(hand_id=stream[0].event.hand_id, expected_sequence=0, events=stream)


def test_terminal_hand_creates_time_bounded_review_with_hero_nodes(tmp_path):
    path = tmp_path / "auto-review.sqlite3"
    events = SQLiteHandEventStore(path)
    stream = _stream()
    _append(events, stream)
    reviews = SQLiteReviewProjectionStore(path)
    service = AutomaticReviewProjectionService(events, reviews)

    review = service.apply_hand(
        session_id="review-session", hand_id="review-session:hand:1", hero_seat=0
    )

    assert review is not None
    assert review.completion_sequence == 4
    assert review.hero_decisions[0].action_event_id == "review-event-2"
    assert review.hero_decisions[0].visible_prefix_event_ids == ("review-event-1",)
    assert review.hero_decisions[0].visible_action_count == 0
    assert review.references.stats.status == "unavailable"
    assert review.references.formula.status == "unavailable"
    assert review.references.belief.status == "unavailable"
    assert review.references.hand_lab.status == "unavailable"
    events.close()
    reviews.close()


def test_missing_terminal_does_not_generate_review_and_restart_is_idempotent(tmp_path):
    path = tmp_path / "auto-review-restart.sqlite3"
    events = SQLiteHandEventStore(path)
    incomplete = _stream(terminal=False)
    _append(events, incomplete)
    reviews = SQLiteReviewProjectionStore(path)
    service = AutomaticReviewProjectionService(events, reviews)

    assert service.apply_hand(session_id="review-session", hand_id=incomplete[0].event.hand_id, hero_seat=0) is None
    events.close()
    reviews.close()

    completed_events = SQLiteHandEventStore(path)
    completed = _stream()
    completed_events.append(hand_id=completed[0].event.hand_id, expected_sequence=3, events=(completed[-1],))
    restarted_reviews = SQLiteReviewProjectionStore(path)
    restarted = AutomaticReviewProjectionService(completed_events, restarted_reviews)
    first = restarted.apply_hand(session_id="review-session", hand_id=completed[0].event.hand_id, hero_seat=0)
    duplicate = restarted.apply_hand(session_id="review-session", hand_id=completed[0].event.hand_id, hero_seat=0)

    assert duplicate == first
    assert restarted_reviews.count() == 1
    completed_events.close()
    restarted_reviews.close()


def test_completion_followed_by_future_event_is_rejected_not_reviewed(tmp_path):
    path = tmp_path / "auto-review-future.sqlite3"
    events = SQLiteHandEventStore(path)
    stream = _stream()
    _append(events, stream)
    reviews = SQLiteReviewProjectionStore(path)
    service = AutomaticReviewProjectionService(events, reviews)
    future = _event(
        sequence=5,
        payload={
            "kind": "action_taken",
            "street": "preflop",
            "actorSeat": 0,
            "action": "check",
            "amountSemantics": "none",
        },
    )
    events.append(hand_id=future.event.hand_id, expected_sequence=4, events=(future,))

    with pytest.raises(ReviewProjectionError) as caught:
        service.apply_hand(session_id="review-session", hand_id=future.event.hand_id, hero_seat=0)

    assert caught.value.code == "invalid_event_stream"
    assert reviews.count() == 0
    events.close()
    reviews.close()
