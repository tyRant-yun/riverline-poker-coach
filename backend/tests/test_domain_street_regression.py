"""Regression: the domain street must follow the dealt board, not
PokerKit's advance street_index (which moves to the next street as soon
as betting closes, before any cards are dealt).
"""

import pytest

from poker_coach.domain.models import ScenarioSpec, Street
from poker_coach.rules import PokerKitAdapter, ReplayError


def hu_scenario(history, *, decision_actor, after_sequence, board=()):
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
            {"seatId": 0, "startingStack": 10000, "position": "button"},
            {"seatId": 1, "startingStack": 10000, "position": "big_blind"},
        ],
        "heroHoleCards": ["As", "Kd"],
        "villainHoleCards": ["Qh", "Jc"],
        "board": list(board),
        "actionHistory": history,
        "decisionPoint": {
            "street": "preflop",
            "actorSeat": decision_actor,
            "afterSequence": after_sequence,
        },
        "assumptions": {},
    }
    return ScenarioSpec.model_validate(payload)


def ev(sequence, actor, action_type, street="preflop", amount=None, amount_type="none"):
    event = {
        "actionId": f"a{sequence}",
        "sequence": sequence,
        "street": street,
        "actorSeat": actor,
        "actionType": action_type,
    }
    if amount is not None:
        event["amount"] = amount
        event["amountType"] = amount_type
    return event


class TestDomainStreetFollowsBoard:
    def test_preflop_complete_before_flop_is_still_preflop(self):
        # BTN calls, BB checks: preflop betting is over but no flop is
        # dealt yet. The street must remain preflop (board is empty).
        scenario = hu_scenario(
            [
                ev(1, 0, "call", amount=50, amount_type="cost"),
                ev(2, 1, "check"),
            ],
            decision_actor=1,
            after_sequence=2,
        )
        result = PokerKitAdapter().replay_to_decision(scenario)
        state = result.final_state
        assert state.street is Street.PREFLOP
        assert state.board == ()
        assert state.actor_seat is None

    def test_flop_dealt_is_flop(self):
        scenario = hu_scenario(
            [
                ev(1, 0, "call", amount=50, amount_type="cost"),
                ev(2, 1, "check"),
                ev(3, 1, "deal_flop", street="flop"),
            ],
            decision_actor=1,
            after_sequence=3,
            board=["2c", "7d", "Jh"],
        )
        scenario = scenario.model_copy(
            update={"decision_point": scenario.decision_point.model_copy(
                update={"street": Street.FLOP}
            )}
        )
        result = PokerKitAdapter().replay_to_decision(scenario)
        assert result.final_state.street is Street.FLOP

    def test_turn_complete_before_turn_card_is_flop(self):
        # Flop betting checked through; the turn street_index advances but
        # no turn card is on the board yet.
        scenario = hu_scenario(
            [
                ev(1, 0, "call", amount=50, amount_type="cost"),
                ev(2, 1, "check"),
                ev(3, 1, "deal_flop", street="flop"),
                ev(4, 1, "check", street="flop"),
                ev(5, 0, "check", street="flop"),
            ],
            decision_actor=0,
            after_sequence=5,
            board=["2c", "7d", "Jh"],
        )
        result = PokerKitAdapter().replay_to_decision(scenario)
        assert result.final_state.street is Street.FLOP
        assert result.final_state.board == ("2c", "7d", "Jh")

    def test_turn_card_dealt_is_turn(self):
        scenario = hu_scenario(
            [
                ev(1, 0, "call", amount=50, amount_type="cost"),
                ev(2, 1, "check"),
                ev(3, 1, "deal_flop", street="flop"),
                ev(4, 1, "check", street="flop"),
                ev(5, 0, "check", street="flop"),
                ev(6, 0, "deal_turn", street="turn"),
            ],
            decision_actor=1,
            after_sequence=6,
            board=["2c", "7d", "Jh", "9s"],
        )
        scenario = scenario.model_copy(
            update={"decision_point": scenario.decision_point.model_copy(
                update={"street": Street.TURN}
            )}
        )
        result = PokerKitAdapter().replay_to_decision(scenario)
        assert result.final_state.street is Street.TURN

    def test_showdown_is_complete(self):
        scenario = hu_scenario(
            [
                ev(1, 0, "call", amount=50, amount_type="cost"),
                ev(2, 1, "check"),
                ev(3, 1, "deal_flop", street="flop"),
                ev(4, 1, "check", street="flop"),
                ev(5, 0, "check", street="flop"),
                ev(6, 0, "deal_turn", street="turn"),
                ev(7, 1, "check", street="turn"),
                ev(8, 0, "check", street="turn"),
                ev(9, 0, "deal_river", street="river"),
                ev(10, 1, "check", street="river"),
                ev(11, 0, "check", street="river"),
                ev(12, 1, "showdown", street="showdown"),
            ],
            decision_actor=1,
            after_sequence=12,
            board=["2c", "7d", "Jh", "9s", "3h"],
        )
        scenario = scenario.model_copy(
            update={"decision_point": scenario.decision_point.model_copy(
                update={"street": Street.SHOWDOWN}
            )}
        )
        result = PokerKitAdapter().replay_to_decision(scenario)
        assert result.final_state.street is Street.COMPLETE
