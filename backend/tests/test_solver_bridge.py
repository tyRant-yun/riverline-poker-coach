"""Phase 8E: HU solver bridge — two active players at a multiway table.

The sidecar is a heads-up postflop solver; a multiway table is solvable
when exactly two players remain at the decision point. Effective stack
covers only those two players, and bunching is recorded as an explicit
approximation.
"""

import pytest

from poker_coach.domain.models import RangeSpec, ScenarioSpec, positions_for_table
from poker_coach.rules import PokerKitAdapter
from poker_coach.solver.adapter import build_spot, range_to_string
from poker_coach.solver.types import SolverUnsupportedError


def multiway_scenario(table_size, *, button_seat=0, hero_seat=0, stacks=None, **overrides):
    stacks = stacks or [10_000] * table_size
    positions = [p.value for p in positions_for_table(table_size)]
    seats = [
        {
            "seatId": seat_id,
            "startingStack": stacks[seat_id],
            "position": positions[(seat_id - button_seat) % table_size],
        }
        for seat_id in range(table_size)
    ]
    payload = {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": table_size,
        "smallBlind": 50,
        "bigBlind": 100,
        "ante": 0,
        "buttonSeat": button_seat,
        "heroSeat": hero_seat,
        "seats": seats,
        "knownHoleCardsBySeat": {hero_seat: ["As", "Kd"]},
        "board": [],
        "actionHistory": [],
        "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
        "assumptions": {},
    }
    payload.update(overrides)
    return ScenarioSpec.model_validate(payload)


def action(sequence, actor_seat, action_type, street="preflop", amount=None, amount_type="none"):
    event = {
        "actionId": f"a{sequence}",
        "sequence": sequence,
        "street": street,
        "actorSeat": actor_seat,
        "actionType": action_type,
    }
    if amount is not None:
        event["amount"] = amount
        event["amountType"] = amount_type
    return event


def range_spec(label: str, entry: str) -> RangeSpec:
    return RangeSpec.model_validate(
        {
            "rangeId": f"test-{label}",
            "name": label,
            "version": "1",
            "source": "user_defined",
            "matrix169": {entry: "1"},
        }
    )


# Preflop: UTG/MP fold, CO folds, BTN raises, SB folds, BB calls, flop dealt.
# Live at the flop: BTN (seat 0) and BB (hero, seat 2).
BRIDGE_HISTORY = [
    action(1, 3, "fold"),
    action(2, 4, "fold"),
    action(3, 5, "fold"),
    action(4, 0, "raise_to", amount=300, amount_type="to"),
    action(5, 1, "fold"),
    action(6, 2, "call", amount=200, amount_type="cost"),
    action(7, 1, "deal_flop", street="flop"),
]
BRIDGE_DECISION = {"street": "flop", "actorSeat": 2, "afterSequence": 7}
FULL_BOARD = ["2c", "7d", "Jh"]


class TestHuBridgeBuilds:
    def test_6max_two_active_players_builds_a_spot(self):
        scenario = multiway_scenario(
            6,
            hero_seat=2,
            board=FULL_BOARD,
            actionHistory=BRIDGE_HISTORY,
            decisionPoint=BRIDGE_DECISION,
        )
        spot = build_spot(
            scenario,
            hero_range=range_spec("BB", "22"),
            villain_range=range_spec("BTN", "AKs"),
        )
        assert spot.street.value == "flop"
        assert spot.oop_range == range_to_string(range_spec("BB", "22"))
        assert spot.ip_range == range_to_string(range_spec("BTN", "AKs"))
        # BB is out of position postflop (button acts last).
        # 10000 - 200 = 9800 BB, 10000 - 300 = 9700 BTN.
        assert spot.effective_stack == 9700
        # The table was multiway, so the bunching approximation is recorded.
        assert spot.assumptions == ("bunching_ignored",)

    def test_effective_stack_ignores_folded_short_stacks(self):
        stacks = [8_000, 2_000, 9_000, 5_000, 10_000, 10_000]
        scenario = multiway_scenario(
            6,
            hero_seat=2,
            stacks=stacks,
            board=FULL_BOARD,
            actionHistory=BRIDGE_HISTORY,
            decisionPoint=BRIDGE_DECISION,
        )
        spot = build_spot(
            scenario,
            hero_range=range_spec("BB", "22"),
            villain_range=range_spec("BTN", "AKs"),
        )
        # Active stacks: BTN 7700 (8000-300), BB 8800 (9000-200).
        # The folded 1950 SB stack must not drag the spot down.
        assert spot.effective_stack == 7700

    def test_button_folded_oop_is_the_next_live_player(self):
        # Same hand but the button folds too: only BB and UTG remain.
        history = [
            action(1, 3, "raise_to", amount=300, amount_type="to"),
            action(2, 4, "fold"),
            action(3, 5, "fold"),
            action(4, 0, "fold"),
            action(5, 1, "fold"),
            action(6, 2, "call", amount=200, amount_type="cost"),
            action(7, 1, "deal_flop", street="flop"),
        ]
        scenario = multiway_scenario(
            6,
            hero_seat=2,
            board=FULL_BOARD,
            actionHistory=history,
            decisionPoint=BRIDGE_DECISION,
        )
        spot = build_spot(
            scenario,
            hero_range=range_spec("BB", "22"),
            villain_range=range_spec("UTG", "88"),
        )
        # Live players: BB (2) and UTG (3). BB is first clockwise from the
        # button (seat 0 folded), so BB remains OOP and his range is oop_range.
        assert spot.oop_range == range_to_string(range_spec("BB", "22"))
        assert spot.ip_range == range_to_string(range_spec("UTG", "88"))
        assert spot.effective_stack == 9_700  # min(9800, 9700)

    def test_hu_table_has_no_bunching_assumption(self):
        scenario = multiway_scenario(
            2,
            hero_seat=0,
            board=FULL_BOARD,
            actionHistory=[
                action(1, 0, "raise_to", amount=300, amount_type="to"),
                action(2, 1, "call", amount=200, amount_type="cost"),
                action(3, 1, "deal_flop", street="flop"),
            ],
            decisionPoint={"street": "flop", "actorSeat": 1, "afterSequence": 3},
        )
        spot = build_spot(
            scenario,
            hero_range=range_spec("BTN", "AKs"),
            villain_range=range_spec("BB", "22"),
        )
        assert spot.assumptions == ()
        assert spot.effective_stack == 9_700


class TestHuBridgeBoundaries:
    def test_three_active_players_rejected(self):
        scenario = multiway_scenario(
            6,
            hero_seat=2,
            board=FULL_BOARD,
            actionHistory=[
                action(1, 3, "raise_to", amount=300, amount_type="to"),
                action(2, 4, "call", amount=300, amount_type="cost"),
                action(3, 5, "fold"),
                action(4, 0, "fold"),
                action(5, 1, "fold"),
                action(6, 2, "call", amount=200, amount_type="cost"),
                action(7, 1, "deal_flop", street="flop"),
            ],
            decisionPoint=BRIDGE_DECISION,
        )
        with pytest.raises(SolverUnsupportedError, match="3 active players"):
            build_spot(scenario)

    def test_8max_multi_active_players_rejected(self):
        scenario = multiway_scenario(
            8,
            hero_seat=2,
            board=FULL_BOARD,
            actionHistory=[
                action(1, 3, "call", amount=100, amount_type="cost"),
                action(2, 4, "call", amount=100, amount_type="cost"),
                action(3, 5, "fold"),
                action(4, 6, "fold"),
                action(5, 7, "fold"),
                action(6, 0, "call", amount=100, amount_type="cost"),
                action(7, 1, "call", amount=50, amount_type="cost"),
                action(8, 2, "check"),
                action(9, 1, "deal_flop", street="flop"),
            ],
            decisionPoint={"street": "flop", "actorSeat": 1, "afterSequence": 9},
        )
        with pytest.raises(SolverUnsupportedError, match="5 active players"):
            build_spot(scenario)


class TestHuBridgeReplayIntegration:
    def test_replay_to_decision_reaches_the_bridge_spot(self):
        scenario = multiway_scenario(
            6,
            hero_seat=2,
            board=FULL_BOARD,
            actionHistory=BRIDGE_HISTORY,
            decisionPoint=BRIDGE_DECISION,
        )
        replay = PokerKitAdapter().replay_to_decision(scenario)
        assert len(replay.final_state.stacks) == 6
        spot = build_spot(
            scenario,
            hero_range=range_spec("BB", "22"),
            villain_range=range_spec("BTN", "AKs"),
            replay=replay,
        )
        assert spot.starting_pot == 650  # 150 blinds + BTN 300 + BB 200
