import pytest

from poker_coach.domain.models import ScenarioSpec
from poker_coach.rules import PokerKitAdapter, ReplayError


def make_scenario(action_history, *, board=None, villain_hole_cards=None, stacks=None):
    stacks = stacks or (10_000, 10_000)
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
                {"seatId": 0, "startingStack": stacks[0], "position": "button"},
                {"seatId": 1, "startingStack": stacks[1], "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "villainHoleCards": villain_hole_cards,
            "board": board or [],
            "actionHistory": action_history,
            "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
            "assumptions": {},
        }
    )


def golden_scenarios():
    yield "fresh", make_scenario([])
    yield "fold", make_scenario(
        [
            {
                "actionId": "raise",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "raise_to",
                "amount": 300,
                "amountType": "to",
            },
            {
                "actionId": "fold",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "fold",
            },
        ]
    )
    yield "all-in", make_scenario(
        [
            {
                "actionId": "jam",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "all_in",
                "amount": 1_000,
                "amountType": "to",
            },
            {
                "actionId": "call-jam",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 900,
                "amountType": "cost",
            },
        ],
        board=["2c", "3d", "4h", "5s", "9c"],
        villain_hole_cards=["Qh", "Jc"],
        stacks=(1_000, 1_000),
    )
    yield "split", make_scenario(
        [
            {
                "actionId": "jam",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "all_in",
                "amount": 1_000,
                "amountType": "to",
            },
            {
                "actionId": "call-jam",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 900,
                "amountType": "cost",
            },
        ],
        board=["Qs", "Jc", "Ts", "2d", "3h"],
        villain_hole_cards=["Ac", "Kh"],
        stacks=(1_000, 1_000),
    )


@pytest.mark.parametrize(
    ("name", "scenario"),
    list(golden_scenarios()),
    ids=["fresh", "fold", "all-in", "split"],
)
def test_golden_replays_preserve_core_invariants(name, scenario):
    del name
    result = PokerKitAdapter().replay(scenario)
    expected_total = sum(seat.starting_stack for seat in scenario.seats)

    for snapshot in result.snapshots + (result.final_state,):
        assert sum(snapshot.stacks.values()) + snapshot.pot == expected_total
        assert snapshot.pot >= 0
        assert all(amount >= 0 for amount in snapshot.stacks.values())
        assert all(amount >= 0 for amount in snapshot.bets.values())
        assert len(snapshot.board) == len(set(snapshot.board))
        if not snapshot.hand_in_progress:
            assert snapshot.pot == 0
            assert snapshot.legal_actions.actions == ()

    if result.settlement.completed:
        assert result.final_state.pot == 0
        assert result.settlement.total_awarded == sum(result.settlement.payouts.values())
        assert not set(result.settlement.payouts).intersection(result.final_state.folded_seats)


@pytest.mark.parametrize(
    ("name", "scenario"),
    list(golden_scenarios()),
    ids=["fresh", "fold", "all-in", "split"],
)
def test_golden_replay_is_deterministic_and_does_not_mutate_scenario(name, scenario):
    del name
    before = scenario.to_json()
    adapter = PokerKitAdapter()

    first = adapter.replay(scenario)
    second = adapter.replay(scenario)

    assert first.to_json() == second.to_json()
    assert scenario.to_json() == before


def test_invalid_event_keeps_input_immutable_and_reports_current_legal_actions():
    scenario = make_scenario(
        [
            {
                "actionId": "illegal-check",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "check",
            }
        ]
    )
    before = scenario.to_json()

    with pytest.raises(ReplayError) as error:
        PokerKitAdapter().replay(scenario)

    assert error.value.code == "check_not_legal"
    assert error.value.sequence == 1
    assert error.value.state is not None
    assert error.value.state.actor_seat == 0
    assert error.value.state.legal_actions.actions
    assert scenario.to_json() == before
