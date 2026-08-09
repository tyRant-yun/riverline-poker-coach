import pytest

from poker_coach.domain.models import ActionType, ScenarioSpec
from poker_coach.rules import PokerKitAdapter, ReplayError


def scenario_with_history(action_history=None, board=None, villain_hole_cards=None, **extra):
    payload = {
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
            "villainHoleCards": villain_hole_cards,
            "board": board or [],
            "actionHistory": action_history or [],
            "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
            "assumptions": {},
        }
    payload.update(extra)
    return ScenarioSpec.model_validate(payload)


def checkdown_history(*, river_action=None):
    events = [
        {
            "actionId": "call",
            "sequence": 1,
            "street": "preflop",
            "actorSeat": 0,
            "actionType": "call",
            "amount": 50,
            "amountType": "cost",
        },
        {
            "actionId": "check-pf",
            "sequence": 2,
            "street": "preflop",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "flop",
            "sequence": 3,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "deal_flop",
        },
        {
            "actionId": "check-flop-bb",
            "sequence": 4,
            "street": "flop",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-flop-btn",
            "sequence": 5,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "check",
        },
        {
            "actionId": "turn",
            "sequence": 6,
            "street": "turn",
            "actorSeat": 0,
            "actionType": "deal_turn",
        },
        {
            "actionId": "check-turn-bb",
            "sequence": 7,
            "street": "turn",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-turn-btn",
            "sequence": 8,
            "street": "turn",
            "actorSeat": 0,
            "actionType": "check",
        },
        {
            "actionId": "river",
            "sequence": 9,
            "street": "river",
            "actorSeat": 0,
            "actionType": "deal_river",
        },
        {
            "actionId": "check-river-bb",
            "sequence": 10,
            "street": "river",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-river-btn",
            "sequence": 11,
            "street": "river",
            "actorSeat": 0,
            "actionType": "check",
        },
    ]
    if river_action is not None:
        events[-1] = river_action
    return events


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


def test_known_all_in_auto_runs_out_and_settles_with_explicit_markers():
    scenario = scenario_with_history(
        [
            {
                "actionId": "jam",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "all_in",
                "amount": 10_000,
                "amountType": "to",
            },
            {
                "actionId": "call-jam",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 9_900,
                "amountType": "cost",
            },
            {
                "actionId": "showdown",
                "sequence": 3,
                "street": "showdown",
                "actorSeat": 0,
                "actionType": "showdown",
            },
            {
                "actionId": "award",
                "sequence": 4,
                "street": "complete",
                "actorSeat": 0,
                "actionType": "award_pot",
                "amount": 20_000,
                "amountType": "award",
            },
        ],
        board=["2c", "3d", "4h", "5s", "9c"],
        villain_hole_cards=["Qh", "Jc"],
    )

    result = PokerKitAdapter().replay(scenario)

    assert result.final_state.board == ("2c", "3d", "4h", "5s", "9c")
    assert result.final_state.pot == 0
    assert result.final_state.hand_in_progress is False
    assert result.final_state.stacks == {0: 20_000, 1: 0}
    assert result.settlement.completed
    assert result.settlement.reason == "showdown"
    assert result.settlement.winner_seats == (0,)
    assert result.settlement.payouts == {0: 20_000}


def test_fold_settles_without_awarding_the_folded_player():
    result = PokerKitAdapter().replay(
        scenario_with_history(
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
    )

    assert result.final_state.pot == 0
    assert result.final_state.hand_in_progress is False
    assert result.final_state.folded_seats == (1,)
    assert result.settlement.reason == "fold"
    assert result.settlement.winner_seats == (0,)
    assert result.settlement.payouts == {0: 100}


def test_split_pot_uses_pokerkit_tie_resolution():
    action_history = [
        {
            "actionId": "call",
            "sequence": 1,
            "street": "preflop",
            "actorSeat": 0,
            "actionType": "call",
            "amount": 50,
            "amountType": "cost",
        },
        {
            "actionId": "check-pf",
            "sequence": 2,
            "street": "preflop",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "flop",
            "sequence": 3,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "deal_flop",
        },
        {
            "actionId": "check-flop-bb",
            "sequence": 4,
            "street": "flop",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-flop-btn",
            "sequence": 5,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "check",
        },
        {
            "actionId": "turn",
            "sequence": 6,
            "street": "turn",
            "actorSeat": 0,
            "actionType": "deal_turn",
        },
        {
            "actionId": "check-turn-bb",
            "sequence": 7,
            "street": "turn",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-turn-btn",
            "sequence": 8,
            "street": "turn",
            "actorSeat": 0,
            "actionType": "check",
        },
        {
            "actionId": "river",
            "sequence": 9,
            "street": "river",
            "actorSeat": 0,
            "actionType": "deal_river",
        },
        {
            "actionId": "check-river-bb",
            "sequence": 10,
            "street": "river",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "check-river-btn",
            "sequence": 11,
            "street": "river",
            "actorSeat": 0,
            "actionType": "check",
        },
    ]
    result = PokerKitAdapter().replay(
        scenario_with_history(
            action_history,
            board=["Qs", "Jc", "Ts", "2d", "3h"],
            villain_hole_cards=["Ac", "Kh"],
        )
    )

    assert result.settlement.completed
    assert result.settlement.winner_seats == (0, 1)
    assert result.settlement.payouts == {0: 100, 1: 100}
    assert result.settlement.odd_chip_rule == "first_eligible_winner_in_pot_order"
    assert result.final_state.pot == 0
    assert sum(result.final_state.stacks.values()) == 20_000


def test_illegal_event_error_contains_state_and_legal_actions():
    scenario = scenario_with_history(
        [
            {
                "actionId": "bad-check",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "check",
            }
        ]
    )

    with pytest.raises(ReplayError) as error:
        PokerKitAdapter().replay(scenario)

    assert error.value.code == "check_not_legal"
    assert error.value.sequence == 1
    assert error.value.state is not None
    assert "call" in [action.value for action in error.value.state.legal_actions.actions]
    assert error.value.as_dict()["legalActions"]["actions"]


def test_limped_pot_and_minimum_raise_have_conserved_chips():
    limped = PokerKitAdapter().replay(
        scenario_with_history(
            [
                {
                    "actionId": "limp",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
            ]
        )
    )
    assert limped.final_state.pot == 200
    assert sum(limped.final_state.stacks.values()) + limped.final_state.pot == 20_000

    minimum_raise = PokerKitAdapter().replay(
        scenario_with_history(
            [
                {
                    "actionId": "min-raise",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "raise_to",
                    "amount": 200,
                    "amountType": "to",
                },
                {
                    "actionId": "call",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "call",
                    "amount": 100,
                    "amountType": "cost",
                },
            ]
        )
    )
    assert minimum_raise.final_state.pot == 400
    assert minimum_raise.final_state.stacks == {0: 9_800, 1: 9_800}


def test_three_bet_four_bet_replay_uses_raise_to_totals():
    result = PokerKitAdapter().replay(
        scenario_with_history(
            [
                {
                    "actionId": "open",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "raise_to",
                    "amount": 300,
                    "amountType": "to",
                },
                {
                    "actionId": "three-bet",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "raise_to",
                    "amount": 900,
                    "amountType": "to",
                },
                {
                    "actionId": "four-bet",
                    "sequence": 3,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "raise_to",
                    "amount": 2_100,
                    "amountType": "to",
                },
                {
                    "actionId": "call-four-bet",
                    "sequence": 4,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "call",
                    "amount": 1_200,
                    "amountType": "cost",
                },
            ]
        )
    )
    assert result.final_state.pot == 4_200
    assert result.final_state.stacks == {0: 7_900, 1: 7_900}


def test_short_all_in_below_full_raise_is_legal_and_runs_out():
    scenario = scenario_with_history(
        [
            {
                "actionId": "open",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "raise_to",
                "amount": 200,
                "amountType": "to",
            },
            {
                "actionId": "short-jam",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "all_in",
                "amount": 250,
                "amountType": "to",
            },
            {
                "actionId": "call-short-jam",
                "sequence": 3,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            },
        ],
        board=["2c", "3d", "4h", "5s", "9c"],
        villain_hole_cards=["Qh", "Jc"],
        seats=[
            {"seatId": 0, "startingStack": 1_000, "position": "button"},
            {"seatId": 1, "startingStack": 250, "position": "big_blind"},
        ],
    )
    result = PokerKitAdapter().replay(scenario)

    assert result.final_state.pot == 0
    assert result.final_state.stacks == {0: 1_250, 1: 0}
    assert result.settlement.completed
    assert result.settlement.winner_seats == (0,)
    assert sum(result.final_state.stacks.values()) == 1_250


@pytest.mark.filterwarnings("ignore:There is no reason for this player to fold")
def test_flop_fold_pays_the_unfolded_player_directly():
    result = PokerKitAdapter().replay(
        scenario_with_history(
            [
                {
                    "actionId": "limp",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check-pf",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "flop",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 0,
                    "actionType": "deal_flop",
                },
                {
                    "actionId": "fold-flop",
                    "sequence": 4,
                    "street": "flop",
                    "actorSeat": 1,
                    "actionType": "fold",
                },
            ],
            board=["2c", "7d", "Jh"],
        )
    )
    assert result.final_state.pot == 0
    assert result.settlement.reason == "fold"
    assert result.settlement.payouts == {0: 200}
    assert 1 not in result.settlement.payouts


def test_river_call_reaches_showdown_and_pays_pot():
    events = checkdown_history()
    events[-2:] = [
        {
            "actionId": "check-river-bb",
            "sequence": 10,
            "street": "river",
            "actorSeat": 1,
            "actionType": "check",
        },
        {
            "actionId": "river-bet",
            "sequence": 11,
            "street": "river",
            "actorSeat": 0,
            "actionType": "bet",
            "amount": 100,
            "amountType": "by",
        },
        {
            "actionId": "river-call",
            "sequence": 12,
            "street": "river",
            "actorSeat": 1,
            "actionType": "call",
            "amount": 100,
            "amountType": "cost",
        },
    ]
    result = PokerKitAdapter().replay(
        scenario_with_history(
            events,
            board=["2c", "7d", "Jh", "4s", "9c"],
            villain_hole_cards=["Qh", "Jc"],
        )
    )
    assert result.final_state.street.value == "complete"
    assert result.final_state.pot == 0
    assert result.settlement.completed
    assert result.settlement.total_awarded == 400


def test_best_five_kicker_comparison_selects_single_winner():
    result = PokerKitAdapter().replay(
        scenario_with_history(
            checkdown_history(),
            board=["As", "Kd", "7c", "3h", "2s"],
            heroHoleCards=["Ac", "Qd"],
            villain_hole_cards=["Ah", "Jc"],
        )
    )
    assert result.settlement.winner_seats == (0,)
    assert result.settlement.payouts == {0: 200}


def test_board_best_five_can_force_a_split():
    result = PokerKitAdapter().replay(
        scenario_with_history(
            checkdown_history(),
            board=["2c", "3d", "4h", "5s", "6c"],
            villain_hole_cards=["Qh", "Jc"],
        )
    )
    assert result.settlement.winner_seats == (0, 1)
    assert result.settlement.payouts == {0: 100, 1: 100}


def test_repeated_action_is_rejected_without_mutating_the_input():
    scenario = scenario_with_history(
        [
            {
                "actionId": "call",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            },
            {
                "actionId": "check",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "check",
            },
            {
                "actionId": "repeated-check",
                "sequence": 3,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "check",
            },
        ]
    )
    before = scenario.to_json()
    with pytest.raises(ReplayError) as error:
        PokerKitAdapter().replay(scenario)
    assert error.value.code == "wrong_actor"
    assert error.value.sequence == 3
    assert error.value.state is not None
    assert scenario.to_json() == before


def test_wrong_street_and_illegal_bet_report_the_first_invalid_event():
    wrong_street = scenario_with_history(
        [
            {
                "actionId": "wrong-street",
                "sequence": 1,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            }
        ]
    )
    with pytest.raises(ReplayError) as street_error:
        PokerKitAdapter().replay(wrong_street)
    assert street_error.value.code == "wrong_street"
    assert street_error.value.sequence == 1
    assert street_error.value.state is not None

    illegal_bet = scenario_with_history(
        [
            {
                "actionId": "call",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            },
            {
                "actionId": "check",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "check",
            },
            {
                "actionId": "flop",
                "sequence": 3,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "deal_flop",
            },
            {
                "actionId": "small-bet",
                "sequence": 4,
                "street": "flop",
                "actorSeat": 1,
                "actionType": "bet",
                "amount": 10,
                "amountType": "by",
            },
        ],
        board=["2c", "7d", "Jh"],
    )
    with pytest.raises(ReplayError) as bet_error:
        PokerKitAdapter().replay(illegal_bet)
    assert bet_error.value.code == "raise_amount_out_of_range"
    assert bet_error.value.sequence == 4
    assert bet_error.value.state is not None


@pytest.mark.parametrize(
    ("action_type", "amount", "amount_type", "expected_code"),
    [
        ("call", 49, "cost", "call_amount_mismatch"),
        ("raise_to", 199, "to", "raise_amount_out_of_range"),
        ("raise_to", 10_001, "to", "raise_amount_out_of_range"),
    ],
)
def test_call_and_raise_bounds_are_enforced(
    action_type, amount, amount_type, expected_code
):
    scenario = scenario_with_history(
        [
            {
                "actionId": "invalid",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": action_type,
                "amount": amount,
                "amountType": amount_type,
            }
        ]
    )
    with pytest.raises(ReplayError) as error:
        PokerKitAdapter().replay(scenario)
    assert error.value.code == expected_code
    assert error.value.sequence == 1
    assert error.value.state is not None


def test_action_after_fold_is_hand_ended_and_duplicate_deal_is_rejected():
    after_fold = scenario_with_history(
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
            {
                "actionId": "late-call",
                "sequence": 3,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 200,
                "amountType": "cost",
            },
        ]
    )
    with pytest.raises(ReplayError) as ended_error:
        PokerKitAdapter().replay(after_fold)
    assert ended_error.value.code == "hand_ended"
    assert ended_error.value.sequence == 3
    assert ended_error.value.state is not None

    duplicate_deal = scenario_with_history(
        [
            {
                "actionId": "call",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            },
            {
                "actionId": "check",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "check",
            },
            {
                "actionId": "flop",
                "sequence": 3,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "deal_flop",
            },
            {
                "actionId": "flop-again",
                "sequence": 4,
                "street": "flop",
                "actorSeat": 1,
                "actionType": "deal_flop",
            },
        ],
        board=["2c", "7d", "Jh"],
    )
    with pytest.raises(ReplayError) as deal_error:
        PokerKitAdapter().replay(duplicate_deal)
    assert deal_error.value.code == "board_order"
    assert deal_error.value.sequence == 4


def test_replay_is_deterministic_and_preserves_chip_conservation():
    scenario = scenario_with_history(
        [
            {
                "actionId": "jam",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "all_in",
                "amount": 10_000,
                "amountType": "to",
            },
            {
                "actionId": "call-jam",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "call",
                "amount": 9_900,
                "amountType": "cost",
            },
        ],
        board=["2c", "3d", "4h", "5s", "9c"],
        villain_hole_cards=["Qh", "Jc"],
    )
    adapter = PokerKitAdapter()
    before = scenario.to_json()
    first = adapter.replay(scenario)
    second = adapter.replay(scenario)

    assert first.to_json() == second.to_json()
    assert scenario.to_json() == before
    assert first.final_state.pot == 0
    assert sum(first.final_state.stacks.values()) == 20_000
