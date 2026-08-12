"""Compatibility evidence for opening authoritative hands in the existing Hand Lab."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from poker_coach.api import create_app
from poker_coach.domain.models import ActionEvent
from poker_coach.persistence import SQLiteHandEventStore
from poker_coach.simulator import (
    HandEventV1,
    HandLabCompatibilityError,
    LegalActionV1,
    GameOrchestrator,
    GameSession,
    OpenHandCommandV1,
    ObservationV1,
    SessionSeatV1,
    player_action_command_from_hand_lab,
    scenario_from_authoritative_events,
)


FIXTURE = Path(__file__).parent / "fixtures" / "simulator-hand-v1.json"


def _fixture_events() -> tuple[HandEventV1, ...]:
    return tuple(
        HandEventV1.model_validate(item)
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


def _sparse_opened_events(tmp_path) -> tuple[HandEventV1, ...]:
    session = GameSession.create(
        session_id="hand-lab-compat",
        seats=tuple(
            SessionSeatV1(seat_id=seat_id, stack=10_000, sitting_out=seat_id in {1, 2})
            for seat_id in range(6)
        ),
    ).start_next_hand()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "hand-lab-compat.sqlite3")
    result = GameOrchestrator(
        store, clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc)
    ).open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-hand-lab-compat",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    store.close()
    return result.appended_events


def test_sparse_authoritative_hand_opens_through_existing_scenario_api_without_leaking_cards(tmp_path):
    bridge = scenario_from_authoritative_events(
        _sparse_opened_events(tmp_path),
        hero_seat=0,
        authorized_hole_card_seat_ids={0},
    )

    assert bridge.compatibility_version == 1
    assert bridge.authoritative_table_size == 6
    assert bridge.active_seat_ids == (0, 3, 4, 5)
    assert bridge.participant_count == 4
    assert bridge.scenario.table_size == 4
    assert tuple(seat.seat_id for seat in bridge.scenario.seats) == (0, 3, 4, 5)
    assert bridge.scenario.hero_seat == 0
    assert bridge.visible_hole_card_seat_ids == (0,)
    assert set(bridge.scenario.known_hole_cards_by_seat) == {0}
    serialized = bridge.to_json()
    assert "2s" not in serialized  # seat 3's seeded cards are not authorized
    assert "Kd" not in serialized

    # This is the unchanged Hand Lab ScenarioSpec endpoint, not a parallel UI API.
    response = TestClient(create_app()).post(
        "/v1/scenarios/validate", json=bridge.scenario.to_dict()
    )
    assert response.status_code == 200, response.text
    assert response.json()["normalizedScenario"]["tableSize"] == 4


def test_bridge_marks_missing_hero_cards_as_degraded_instead_of_inventing_them(tmp_path):
    bridge = scenario_from_authoritative_events(
        _sparse_opened_events(tmp_path)[:1], hero_seat=0
    )

    assert bridge.scenario.known_hole_cards_by_seat == {}
    assert bridge.visible_hole_card_seat_ids == ()
    assert bridge.degradation_reasons == ("hero_hole_cards_not_recorded",)


def test_completed_showdown_requires_visibility_sufficient_to_replay_legacy_hand_lab():
    events = _fixture_events()
    with pytest.raises(HandLabCompatibilityError) as exc_info:
        scenario_from_authoritative_events(
            events, hero_seat=2, authorized_hole_card_seat_ids={2}
        )
    assert exc_info.value.code == "insufficient_visible_facts"

    bridge = scenario_from_authoritative_events(
        events,
        hero_seat=2,
        authorized_hole_card_seat_ids={0, 1, 2, 3, 4, 5},
    )
    assert bridge.scenario.decision_point.street.value == "complete"
    # Authorizing a seat never invents a card that the event stream did not record.
    assert bridge.scenario.known_hole_cards_by_seat.keys() == {0, 2}


def test_bridge_rejects_visibility_for_non_participant_and_invalid_stream():
    events = _fixture_events()
    with pytest.raises(HandLabCompatibilityError) as visibility_error:
        scenario_from_authoritative_events(
            events, hero_seat=2, authorized_hole_card_seat_ids={7}
        )
    assert visibility_error.value.code == "invalid_hole_card_visibility"

    with pytest.raises(Exception) as stream_error:
        scenario_from_authoritative_events((events[1],), hero_seat=2)
    assert getattr(stream_error.value, "code", None) == "out_of_order"


@pytest.mark.parametrize(
    ("payload", "expected_action", "expected_semantics"),
    [
        (
            {"actionType": "fold", "amountType": "none"},
            "fold",
            "none",
        ),
        (
            {"actionType": "check", "amountType": "none"},
            "check",
            "none",
        ),
        (
            {"actionType": "call", "amount": 50, "amountType": "cost"},
            "call",
            "cost",
        ),
        (
            {"actionType": "bet", "amount": 200, "amountType": "by"},
            "bet",
            "by",
        ),
        (
            {"actionType": "raise_to", "amount": 300, "amountType": "to"},
            "raise",
            "to",
        ),
    ],
)
def test_hand_lab_action_mapping_preserves_existing_amount_semantics(
    payload, expected_action, expected_semantics
):
    action = ActionEvent.model_validate(
        {
            "actionId": "hand-lab-action",
            "sequence": 1,
            "street": "preflop",
            "actorSeat": 0,
            **payload,
        }
    )
    command = player_action_command_from_hand_lab(
        session_id="session-1",
        hand_id="hand-1",
        command_id="command-1",
        expected_sequence=7,
        action=action,
    )
    assert command.action.value == expected_action
    assert command.amount_semantics.value == expected_semantics
    assert command.amount == action.amount


def test_hand_lab_action_mapping_refuses_non_player_events():
    action = ActionEvent.model_validate(
        {
            "actionId": "deal-flop",
            "sequence": 1,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "deal_flop",
        }
    )
    with pytest.raises(HandLabCompatibilityError) as exc_info:
        player_action_command_from_hand_lab(
            session_id="session-1",
            hand_id="hand-1",
            command_id="command-1",
            expected_sequence=7,
            action=action,
        )
    assert exc_info.value.code == "unsupported_hand_lab_action"


def test_hand_lab_all_in_uses_the_authoritative_bet_endpoint_without_recalculating_it():
    action = ActionEvent.model_validate(
        {
            "actionId": "all-in",
            "sequence": 1,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "all_in",
            "amount": 1_000,
            "amountType": "to",
        }
    )
    observation = ObservationV1(
        hand_id="hand-1",
        sequence=7,
        observer_seat=0,
        table_size=2,
        button_seat=0,
        street="flop",
        own_hole_cards=("As", "Kd"),
        pot=300,
        stacks={0: 900, 1: 900},
        street_commitments={0: 50, 1: 50},
        active_seats=(0, 1),
        legal_actions=(
            LegalActionV1(
                action="bet", amount_semantics="by", min_amount=100, max_amount=950
            ),
        ),
    )
    command = player_action_command_from_hand_lab(
        session_id="session-1",
        hand_id="hand-1",
        command_id="command-1",
        expected_sequence=7,
        action=action,
        observation=observation,
    )
    assert command.action.value == "bet"
    assert command.amount == 950
    assert command.amount_semantics.value == "by"
