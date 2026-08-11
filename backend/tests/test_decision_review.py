"""Public-seam tests for time-correct hand-review decision snapshots."""

from __future__ import annotations

import pytest

from poker_coach.domain.models import ScenarioSpec
from poker_coach.review import build_decision_snapshots
from poker_coach.rules import ReplayError


def _hu_checkdown_scenario() -> ScenarioSpec:
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
            "board": ["2c", "7d", "Jh", "9s", "3h"],
            "actionHistory": [
                _action(1, 0, "call", amount=50, amount_type="cost"),
                _action(2, 1, "check"),
                _action(3, 0, "deal_flop", street="flop"),
                _action(4, 1, "check", street="flop"),
                _action(5, 0, "check", street="flop"),
                _action(6, 0, "deal_turn", street="turn"),
                _action(7, 1, "check", street="turn"),
                _action(8, 0, "check", street="turn"),
                _action(9, 0, "deal_river", street="river"),
                _action(10, 1, "check", street="river"),
                _action(11, 0, "check", street="river"),
            ],
            "decisionPoint": {"street": "river", "actorSeat": 0, "afterSequence": 11},
            "assumptions": {},
        }
    )


def _action(
    sequence: int,
    actor_seat: int,
    action_type: str,
    *,
    street: str = "preflop",
    amount: int | None = None,
    amount_type: str = "none",
) -> dict[str, object]:
    event: dict[str, object] = {
        "actionId": f"a{sequence}",
        "sequence": sequence,
        "street": street,
        "actorSeat": actor_seat,
        "actionType": action_type,
    }
    if amount is not None:
        event.update(amount=amount, amountType=amount_type)
    return event


def test_builds_time_correct_snapshots_for_every_hu_player_action():
    snapshots = build_decision_snapshots(_hu_checkdown_scenario())

    assert [snapshot.action_id for snapshot in snapshots] == [
        "a1",
        "a2",
        "a4",
        "a5",
        "a7",
        "a8",
        "a10",
        "a11",
    ]
    assert [snapshot.event_sequence for snapshot in snapshots] == [1, 2, 4, 5, 7, 8, 10, 11]
    assert [snapshot.decision_sequence for snapshot in snapshots] == [0, 1, 3, 4, 6, 7, 9, 10]
    assert [snapshot.actor_seat for snapshot in snapshots] == [0, 1, 1, 0, 1, 0, 1, 0]
    assert [len(snapshot.state_before_action.board) for snapshot in snapshots] == [0, 0, 3, 3, 4, 4, 5, 5]
    assert snapshots[2].state_before_action.board == ("2c", "7d", "Jh")
    assert "9s" not in snapshots[2].state_before_action.board
    assert snapshots[2].state_before_action.legal_actions.actor_seat == 1


def test_returns_prior_decisions_after_a_multiway_folded_hand_is_finished():
    scenario = ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": 3,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 1_000, "position": "button"},
                {"seatId": 1, "startingStack": 1_000, "position": "small_blind"},
                {"seatId": 2, "startingStack": 1_000, "position": "big_blind"},
            ],
            "knownHoleCardsBySeat": {0: ["As", "Kd"]},
            "actionHistory": [
                _action(1, 0, "raise_to", amount=300, amount_type="to"),
                _action(2, 1, "fold"),
                _action(3, 2, "fold"),
            ],
            "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 3},
            "assumptions": {},
        }
    )

    snapshots = build_decision_snapshots(scenario)

    assert [snapshot.action_id for snapshot in snapshots] == ["a1", "a2", "a3"]
    assert [snapshot.actor_seat for snapshot in snapshots] == [0, 1, 2]
    assert snapshots[-1].state_before_action.legal_actions.actions


def test_returns_prior_decisions_after_a_multiway_all_in_hand_is_finished():
    scenario = ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": 3,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 3_000, "position": "button"},
                {"seatId": 1, "startingStack": 2_000, "position": "small_blind"},
                {"seatId": 2, "startingStack": 5_000, "position": "big_blind"},
            ],
            "knownHoleCardsBySeat": {
                0: ["As", "Kd"],
                1: ["Qh", "Qc"],
                2: ["7c", "7d"],
            },
            "board": ["2c", "8d", "Jh", "9s", "3h"],
            "actionHistory": [
                _action(1, 0, "raise_to", amount=3_000, amount_type="to"),
                _action(2, 1, "call", amount=1_950, amount_type="cost"),
                _action(3, 2, "call", amount=2_900, amount_type="cost"),
            ],
            "decisionPoint": {"street": "preflop", "actorSeat": 2, "afterSequence": 3},
            "assumptions": {},
        }
    )

    snapshots = build_decision_snapshots(scenario)

    assert [snapshot.action_id for snapshot in snapshots] == ["a1", "a2", "a3"]
    assert [snapshot.actor_seat for snapshot in snapshots] == [0, 1, 2]
    assert snapshots[-1].state_before_action.hand_in_progress
    assert snapshots[-1].state_before_action.legal_actions.actor_seat == 2


def test_reports_the_replay_error_when_a_snapshot_action_has_the_wrong_actor():
    scenario = _hu_checkdown_scenario().model_copy(
        update={
            "action_history": (
                _hu_checkdown_scenario().action_history[0].model_copy(update={"actor_seat": 1}),
            )
        }
    )

    with pytest.raises(ReplayError) as error:
        build_decision_snapshots(scenario)

    assert error.value.code == "wrong_actor"
    assert error.value.sequence == 1
    assert error.value.as_dict()["legalActions"]["actorSeat"] == 0
