"""Phase 8B: golden multiplayer replay tests.

Covers 3-max through 8-max: blind structure, ante, action ordering
(preflop UTG-first, postflop SB-first), fold-through, side pots, split
pots, showdown, chip conservation, and the honest showdown requirement
(known hole cards for every live player).
"""

import pytest

from poker_coach.domain.models import ScenarioSpec, positions_for_table
from poker_coach.rules import PokerKitAdapter, ReplayError

ADAPTER = PokerKitAdapter()


def multiway_scenario(table_size, *, button_seat=0, stacks=None, **overrides):
    """v2 scenario; hero_seat defaults to the button seat."""
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
        "heroSeat": button_seat,
        "seats": seats,
        "knownHoleCardsBySeat": {button_seat: ["As", "Kd"]},
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


def assert_chip_conservation(result, initial_total):
    for snapshot in result.snapshots + (result.final_state,):
        assert sum(snapshot.stacks.values()) + snapshot.pot == initial_total
        assert snapshot.pot >= 0


class TestMultiwayBasics:
    def test_3max_preflop_button_acts_first(self):
        scenario = multiway_scenario(3)
        result = ADAPTER.replay(scenario)
        state = result.final_state
        # 3-max: only the button is left of the big blind preflop.
        assert state.actor_seat == 0
        assert state.pot == 150
        assert_chip_conservation(result, 30_000)

    def test_6max_preflop_utg_acts_first(self):
        scenario = multiway_scenario(6)
        result = ADAPTER.replay(scenario)
        state = result.final_state
        assert state.actor_seat == 3  # UTG
        assert state.pot == 150
        assert state.stacks == {0: 10_000, 1: 9_950, 2: 9_900, 3: 10_000, 4: 10_000, 5: 10_000}
        assert_chip_conservation(result, 60_000)

    def test_8max_utg_plus_one_acts_first_after_utg(self):
        scenario = multiway_scenario(
            8,
            actionHistory=[
                action(1, 3, "call", amount=100, amount_type="cost"),
            ],
        )
        result = ADAPTER.replay(scenario)
        state = result.final_state
        assert state.actor_seat == 4  # utg+1
        assert_chip_conservation(result, 80_000)

    def test_fold_through_to_big_blind(self):
        scenario = multiway_scenario(
            6,
            actionHistory=[
                action(1, 3, "fold"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "fold"),
                action(5, 1, "fold"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        assert settlement.completed
        assert settlement.reason == "fold"
        assert settlement.winner_seats == (2,)
        # PokerKit pushes the pot minus the winner's own blind.
        assert settlement.payouts == {2: 50}
        assert result.final_state.stacks[2] == 10_000 + 50
        assert_chip_conservation(result, 60_000)

    def test_ante_is_collected_from_all_seats(self):
        scenario = multiway_scenario(
            6,
            ante=25,
            actionHistory=[
                action(1, 3, "fold"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "fold"),
                action(5, 1, "fold"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        # Antes (6 x 25) plus blinds (150).
        assert settlement.payouts == {2: 200}
        # BB posts 100 + ante 25, wins the 300 pot -> 10000 - 125 + 300.
        assert result.final_state.stacks[2] == 10_175
        assert_chip_conservation(result, 60_000)


class TestMultiwayActionOrder:
    def test_postflop_actor_is_the_small_blind(self):
        scenario = multiway_scenario(
            6,
            board=["2c", "7d", "Jh"],
            actionHistory=[
                action(1, 3, "call", amount=100, amount_type="cost"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "call", amount=100, amount_type="cost"),
                action(5, 1, "call", amount=50, amount_type="cost"),
                action(6, 2, "check"),
                action(7, 1, "deal_flop", street="flop"),
            ],
        )
        result = ADAPTER.replay(scenario)
        state = result.final_state
        assert state.street.value == "flop"
        # Postflop the small blind acts first.
        assert state.actor_seat == 1
        assert state.pot == 400
        assert_chip_conservation(result, 60_000)

    def test_multiway_raise_three_bet_call_fold(self):
        scenario = multiway_scenario(
            6,
            actionHistory=[
                action(1, 3, "raise_to", amount=300, amount_type="to"),
                action(2, 4, "fold"),
                action(3, 5, "call", amount=300, amount_type="cost"),
                action(4, 0, "fold"),
                action(5, 1, "fold"),
                action(6, 2, "raise_to", amount=900, amount_type="to"),
                action(7, 3, "call", amount=600, amount_type="cost"),
                action(8, 5, "fold"),
            ],
        )
        result = ADAPTER.replay(scenario)
        state = result.final_state
        # Blinds 150 + UTG 300 + CO 300 + BB 800 (raise to 900) + UTG 600 = 2150.
        assert state.pot == 2_150
        assert_chip_conservation(result, 60_000)


class TestSidePotsAndShowdown:
    def test_side_pot_with_three_unequal_all_ins(self):
        scenario = multiway_scenario(
            3,
            stacks=[3_000, 2_000, 5_000],
            board=["2c", "8d", "Jh", "9s", "3h"],
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"], 2: ["7c", "7d"]},
            actionHistory=[
                action(1, 0, "raise_to", amount=3_000, amount_type="to"),
                action(2, 1, "call", amount=1_950, amount_type="cost"),
                action(3, 2, "call", amount=2_900, amount_type="cost"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        assert settlement.completed
        assert settlement.reason == "showdown"
        # Main pot (3 x 2000) to the best hand (QQ); side pot (2 x 1000)
        # between the button and the big blind to the best of those two.
        assert settlement.winner_seats == (1, 2)
        assert settlement.payouts == {1: 6_000, 2: 2_000}
        assert_chip_conservation(result, 10_000)

    def test_multiway_split_pot(self):
        scenario = multiway_scenario(
            3,
            stacks=[3_000, 3_000, 3_000],
            board=["Qs", "Jc", "Ts", "2d", "3h"],
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Ah", "Kh"], 2: []},
            actionHistory=[
                action(1, 0, "raise_to", amount=3_000, amount_type="to"),
                action(2, 1, "call", amount=2_950, amount_type="cost"),
                action(3, 2, "fold"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        assert settlement.completed
        # A fold occurred earlier, but the pot was decided by card comparison.
        assert settlement.reason == "showdown"
        # Both players make the Broadway straight on the board -> split.
        assert settlement.winner_seats == (0, 1)
        # Pot 6100 (3000 + 3000 + folded BB's 100), split into two halves.
        assert sum(settlement.payouts.values()) == 6_100
        assert {seat for seat in settlement.payouts if settlement.payouts[seat] > 0} == {0, 1}
        assert_chip_conservation(result, 9_000)

    def test_showdown_requires_hole_cards_for_all_live_players(self):
        scenario = multiway_scenario(
            6,
            board=["2c", "7d", "Jh", "9s", "3h"],
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"]},
            actionHistory=[
                action(1, 3, "call", amount=100, amount_type="cost"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "call", amount=100, amount_type="cost"),
                action(5, 1, "call", amount=50, amount_type="cost"),
                action(6, 2, "check"),
                action(7, 1, "deal_flop", street="flop"),
                # The SB is still in this hand, so he leads the flop.
                action(8, 1, "check", street="flop"),
                action(9, 2, "check", street="flop"),
                action(10, 3, "check", street="flop"),
                action(11, 0, "check", street="flop"),
                action(12, 1, "deal_turn", street="turn"),
                action(13, 1, "check", street="turn"),
                action(14, 2, "check", street="turn"),
                action(15, 3, "check", street="turn"),
                action(16, 0, "check", street="turn"),
                action(17, 1, "deal_river", street="river"),
                action(18, 1, "check", street="river"),
                action(19, 2, "check", street="river"),
                action(20, 3, "check", street="river"),
                action(21, 0, "check", street="river"),
                action(22, 0, "showdown", street="showdown"),
            ],
        )
        with pytest.raises(ReplayError, match="showdown requires hole cards"):
            ADAPTER.replay(scenario)

    def test_6max_showdown_with_known_cards(self):
        scenario = multiway_scenario(
            6,
            board=["2c", "7d", "Jh", "9s", "3h"],
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"], 2: ["8c", "8h"], 3: ["7c", "7h"]},
            actionHistory=[
                action(1, 3, "raise_to", amount=300, amount_type="to"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "call", amount=300, amount_type="cost"),
                action(5, 1, "fold"),
                action(6, 2, "call", amount=200, amount_type="cost"),
                action(7, 1, "deal_flop", street="flop"),
                # SB folded preflop, so the BB leads the flop.
                action(8, 2, "check", street="flop"),
                action(9, 3, "check", street="flop"),
                action(10, 0, "check", street="flop"),
                action(11, 1, "deal_turn", street="turn"),
                action(12, 2, "check", street="turn"),
                action(13, 3, "check", street="turn"),
                action(14, 0, "check", street="turn"),
                action(15, 1, "deal_river", street="river"),
                action(16, 2, "check", street="river"),
                action(17, 3, "check", street="river"),
                action(18, 0, "check", street="river"),
                action(19, 0, "showdown", street="showdown"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        assert settlement.completed
        assert settlement.reason == "showdown"
        # Board 2c 7d Jh 9s 3h: UTG's 77 trips beat BTN's AK and BB's QQ.
        assert settlement.winner_seats == (3,)
        # Full pot 950 pushed to the winner (PokerKit push semantics).
        assert settlement.payouts[3] == 950
        assert result.final_state.stacks[3] == 10_650
        assert_chip_conservation(result, 60_000)


class TestEightMaxHand:
    def test_8max_full_hand_to_showdown(self):
        scenario = multiway_scenario(
            8,
            board=["2c", "7d", "Jh", "9s", "3h"],
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"], 2: ["8c", "8h"], 3: ["5c", "5h"], 4: ["7c", "7h"]},
            actionHistory=[
                action(1, 3, "call", amount=100, amount_type="cost"),
                action(2, 4, "raise_to", amount=300, amount_type="to"),
                action(3, 5, "fold"),
                action(4, 6, "fold"),
                action(5, 7, "fold"),
                action(6, 0, "call", amount=300, amount_type="cost"),
                action(7, 1, "fold"),
                action(8, 2, "call", amount=200, amount_type="cost"),
                action(9, 3, "call", amount=200, amount_type="cost"),
                action(10, 1, "deal_flop", street="flop"),
                # SB folded preflop, so the BB leads the flop.
                action(11, 2, "check", street="flop"),
                action(12, 3, "check", street="flop"),
                action(13, 4, "check", street="flop"),
                action(14, 0, "check", street="flop"),
                action(15, 1, "deal_turn", street="turn"),
                action(16, 2, "check", street="turn"),
                action(17, 3, "check", street="turn"),
                action(18, 4, "check", street="turn"),
                action(19, 0, "check", street="turn"),
                action(20, 1, "deal_river", street="river"),
                action(21, 2, "check", street="river"),
                action(22, 3, "check", street="river"),
                action(23, 4, "check", street="river"),
                action(24, 0, "check", street="river"),
                action(25, 0, "showdown", street="showdown"),
            ],
        )
        result = ADAPTER.replay(scenario)
        settlement = result.settlement
        assert settlement.completed
        assert settlement.reason == "showdown"
        assert settlement.winner_seats == (4,)
        # Full pot 1250 pushed to the winner (PokerKit push semantics).
        assert settlement.payouts[4] == 1_250
        assert result.final_state.stacks[4] == 10_950
        assert_chip_conservation(result, 80_000)
