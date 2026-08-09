import pytest

from poker_coach.domain.models import ActionType, ScenarioSpec
from poker_coach.rules import PokerKitAdapter, ReplayError


def scenario_with_history(action_history=None, board=None):
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "ante": 0,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "board": board or [],
            "actionHistory": action_history or [],
            "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
            "assumptions": {},
        }
    )


def test_replay_keeps_upstream_state_behind_project_owned_snapshot():
    scenario = scenario_with_history(
        [
            {
                "actionId": "blind-bb",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "post_blind",
                "amount": 100,
                "amountType": "by",
            },
            {
                "actionId": "blind-btn",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "post_blind",
                "amount": 50,
                "amountType": "by",
            },
            {
                "actionId": "raise",
                "sequence": 3,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "raise_to",
                "amount": 300,
                "amountType": "to",
                "potBefore": 150,
                "stackBefore": 9950,
            },
            {
                "actionId": "call",
                "sequence": 4,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 200,
                "amountType": "cost",
                "potBefore": 400,
                "stackBefore": 9900,
            },
        ]
    )

    result = PokerKitAdapter().replay(scenario)

    assert result.rules_engine == "pokerkit"
    assert result.rules_engine_version == "0.7.4"
    assert result.final_state.pot == 600
    assert result.final_state.stacks == {0: 9700, 1: 9700}
    assert result.final_state.actor_seat is None
    assert result.final_state.legal_actions.actions == ()


def test_legal_actions_explain_call_raise_and_fold():
    result = PokerKitAdapter().replay(scenario_with_history())
    actions = result.final_state.legal_actions

    assert actions.actor_seat == 0
    assert actions.call_amount == 50
    assert actions.min_raise_to == 200
    assert actions.max_raise_to == 10_000
    assert ActionType.CALL in actions.actions
    assert ActionType.RAISE_TO in actions.actions
    assert ActionType.FOLD in actions.actions
    assert actions.explanations["raise_to"] == "amount is the total bet after the action"


def test_replay_reports_wrong_actor_at_first_illegal_event():
    scenario = scenario_with_history(
        [
            {
                "actionId": "wrong",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "raise_to",
                "amount": 300,
                "amountType": "to",
            }
        ]
    )

    with pytest.raises(ReplayError, match="expected actor seat 0") as error:
        PokerKitAdapter().replay(scenario)
    assert error.value.code == "wrong_actor"
    assert error.value.sequence == 1


def test_replay_deals_final_board_by_street_events():
    scenario = scenario_with_history(
        [
            {
                "actionId": "blind-bb",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "post_blind",
                "amount": 100,
                "amountType": "by",
            },
            {
                "actionId": "blind-btn",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "post_blind",
                "amount": 50,
                "amountType": "by",
            },
            {
                "actionId": "raise",
                "sequence": 3,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "raise_to",
                "amount": 300,
                "amountType": "to",
            },
            {
                "actionId": "call",
                "sequence": 4,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 200,
                "amountType": "cost",
            },
            {
                "actionId": "flop",
                "sequence": 5,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "deal_flop",
            },
            {
                "actionId": "flop-check-bb",
                "sequence": 6,
                "street": "flop",
                "actorSeat": 1,
                "actionType": "check",
            },
            {
                "actionId": "flop-check-btn",
                "sequence": 7,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "check",
            },
        ],
        board=["2c", "7d", "Jh"],
    )

    result = PokerKitAdapter().replay(scenario)

    assert result.final_state.street.value == "turn"
    assert result.final_state.pot == 600
    assert result.final_state.actor_seat is None


def test_replay_preserves_all_in_state_until_runout():
    scenario = ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 1_000, "position": "button"},
                {"seatId": 1, "startingStack": 1_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "actionHistory": [
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
        }
    )

    result = PokerKitAdapter().replay(scenario)

    assert result.final_state.pot == 2_000
    assert result.final_state.stacks == {0: 0, 1: 0}
    assert result.final_state.hand_in_progress
    assert result.final_state.actor_seat is None
