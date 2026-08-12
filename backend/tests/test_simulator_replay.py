"""Black-box spike tests for event replay and read-model rebuilding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poker_coach.simulator import (
    EventStreamError,
    HandEventV1,
    append_hand_event,
    build_observation,
    replay_hand,
    validate_hand_event_stream,
)


FIXTURE = Path(__file__).parent / "fixtures" / "simulator-hand-v1.json"


def _events() -> tuple[HandEventV1, ...]:
    return tuple(
        HandEventV1.model_validate(item)
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


def test_minimal_6max_fixture_rebuilds_state_and_statistics_deterministically():
    events = _events()

    first = replay_hand(events)
    second = replay_hand(events)

    assert first.state.fingerprint == second.state.fingerprint
    assert first.to_json() == second.to_json()
    assert first.state.applied_sequence == 19
    assert first.state.board == ("2c", "7d", "Jh", "9s", "3h")
    assert first.state.hand_in_progress is False
    assert first.state.winner_seats == (2,)
    assert first.state.payouts == {2: 550}
    assert first.statistics.by_seat[0].vpip is True
    assert first.statistics.by_seat[0].pfr is True
    assert first.statistics.by_seat[2].vpip is True
    assert first.statistics.by_seat[2].pfr is False
    assert all(stat.three_bet is False for stat in first.statistics.by_seat.values())


def test_event_stream_rejects_out_of_order_and_duplicate_events():
    events = _events()
    out_of_order = list(events)
    out_of_order[4], out_of_order[5] = out_of_order[5], out_of_order[4]

    with pytest.raises(EventStreamError) as ordering_error:
        validate_hand_event_stream(out_of_order)
    assert ordering_error.value.code == "out_of_order"

    duplicate = list(events)
    duplicate[1] = duplicate[1].model_copy(update={"event_id": events[0].event_id})
    with pytest.raises(EventStreamError) as duplicate_error:
        validate_hand_event_stream(duplicate)
    assert duplicate_error.value.code == "duplicate_event"

    prefix = events[:-1]
    appended = append_hand_event(prefix, events[-1])
    assert prefix == events[:-1]  # existing events were not mutated or replaced
    assert appended == events


def test_observation_projection_does_not_leak_other_recorded_hole_cards():
    observation = build_observation(_events(), observer_seat=2, after_sequence=10)

    assert observation.own_hole_cards == ("Qh", "Qc")
    assert observation.pot == 550
    assert observation.active_seats == (0, 2)
    assert {action.action.value for action in observation.legal_actions} == {
        "check",
        "bet",
        "fold",
    }
    serialized = observation.to_json()
    assert "As" not in serialized
    assert "Kd" not in serialized
    assert "belief" not in serialized.lower()
