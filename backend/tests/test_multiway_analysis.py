"""Phase 8C: multiway analysis — equityBySeat, activePlayerCount, pot odds."""

from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from poker_coach.analysis.equity import EquityEngine
from poker_coach.analysis.models import InvalidAnalysisInput
from poker_coach.api import create_app
from poker_coach.domain.models import (
    EquityAlgorithm,
    ScenarioSpec,
    positions_for_table,
)


def multiway_scenario(table_size, *, button_seat=0, stacks=None, **overrides):
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


# Monte Carlo keeps the API-level tests fast (a 3-6 hand exact preflop
# enumeration is hundreds of thousands to millions of showdowns).
MC_ASSUMPTIONS = {
    "equityAlgorithm": "monte_carlo",
    "simulationTrials": 500,
    "randomSeed": 7,
}


def api_scenario(table_size, **overrides):
    overrides.setdefault("assumptions", MC_ASSUMPTIONS)
    return multiway_scenario(table_size, **overrides)


ENGINE = EquityEngine()


class TestMultiwayEquityEngine:
    def test_complete_board_hand_vs_hands(self):
        # 2c 7d Jh 9s 3h: trips 7s win outright; AK and QQ have zero equity.
        result = ENGINE.evaluate_multiway(
            [(0, ("As", "Kd")), (1, ("Qh", "Qc")), (2, ("7c", "7h"))],
            ("2c", "7d", "Jh", "9s", "3h"),
        )
        assert result.algorithm is EquityAlgorithm.EXACT_ENUMERATION
        assert result.active_player_count == 3
        assert result.equity_by_seat == {0: Decimal("0"), 1: Decimal("0"), 2: Decimal("1")}
        assert result.tie_probability == Decimal("0")

    def test_multiway_tie_splits_mass(self):
        # Qs Jc Ts 2d 3h: both Broadway hands play the board straight.
        result = ENGINE.evaluate_multiway(
            [(0, ("As", "Kd")), (1, ("Ah", "Kh")), (2, ("8c", "8h"))],
            ("Qs", "Jc", "Ts", "2d", "3h"),
        )
        assert result.equity_by_seat[0] == Decimal("0.5")
        assert result.equity_by_seat[1] == Decimal("0.5")
        assert result.equity_by_seat[2] == Decimal("0")
        assert result.tie_probability == Decimal("1")

    def test_flop_exact_enumeration_is_deterministic_and_conserves(self):
        board = ("2c", "7d", "Jh")
        first = ENGINE.evaluate_multiway(
            [(0, ("Ah", "Kh")), (1, ("Qh", "Qc")), (2, ("6c", "6d"))],
            board,
        )
        second = ENGINE.evaluate_multiway(
            [(0, ("Ah", "Kh")), (1, ("Qh", "Qc")), (2, ("6c", "6d"))],
            board,
        )
        assert first.equity_by_seat == second.equity_by_seat
        assert abs(sum(first.equity_by_seat.values()) - Decimal("1")) < Decimal("1e-9")
        assert all(0 <= share <= 1 for share in first.equity_by_seat.values())

    def test_monte_carlo_is_reproducible_with_seed(self):
        board = ("2c", "7d", "Jh")
        first = ENGINE.evaluate_multiway(
            [(0, ("Ah", "Kh")), (1, ("Qh", "Qc")), (2, ("6c", "6d"))],
            board,
            algorithm=EquityAlgorithm.MONTE_CARLO,
            trials=5_000,
            random_seed=42,
        )
        second = ENGINE.evaluate_multiway(
            [(0, ("Ah", "Kh")), (1, ("Qh", "Qc")), (2, ("6c", "6d"))],
            board,
            algorithm=EquityAlgorithm.MONTE_CARLO,
            trials=5_000,
            random_seed=42,
        )
        assert first.equity_by_seat == second.equity_by_seat
        assert first.standard_errors_by_seat is not None
        assert set(first.standard_errors_by_seat) == set(first.equity_by_seat)

    def test_monte_carlo_requires_seed(self):
        with pytest.raises(InvalidAnalysisInput):
            ENGINE.evaluate_multiway(
                [(0, ("Ah", "Kh")), (1, ("Qh", "Qc"))],
                algorithm=EquityAlgorithm.MONTE_CARLO,
                trials=1_000,
            )

    def test_hand_vs_ranges_weighted_exact(self):
        from poker_coach.domain.models import RangeSpec

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

        # AsKs is crushed by AA and KK on 2c 7d Jh.
        result = ENGINE.evaluate_multiway(
            [
                (0, ("As", "Ks")),
                (1, range_spec("AA", "AA")),
                (2, range_spec("KK", "KK")),
            ],
            ("2c", "7d", "Jh"),
        )
        assert result.weighted
        assert result.active_player_count == 3
        hero = result.equity_by_seat[0]
        assert hero < Decimal("0.5")
        assert abs(sum(result.equity_by_seat.values()) - Decimal("1")) < Decimal("1e-9")

    def test_overlapping_concrete_hands_rejected(self):
        with pytest.raises(InvalidAnalysisInput):
            ENGINE.evaluate_multiway(
                [(0, ("As", "Kd")), (1, ("As", "Kd"))],
                ("2c", "7d", "Jh", "9s", "3h"),
            )


class TestMultiwayAnalysisApi:
    def test_6max_analysis_reports_multiway_equity(self):
        client = TestClient(create_app())
        scenario = api_scenario(
            6,
            knownHoleCardsBySeat={
                0: ["As", "Kd"],
                1: ["Qh", "Qc"],
                2: ["7c", "7h"],
                3: ["8c", "8h"],
                4: ["5c", "5h"],
                5: ["3c", "3h"],
            },
            decisionPoint={"street": "preflop", "actorSeat": 3, "afterSequence": 0},
        )
        response = client.post("/v1/analysis", json=scenario.to_dict())
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        assert analysis["metrics"]["activePlayerCount"] == 6
        multiway = analysis["multiwayEquity"]
        assert multiway is not None
        assert multiway["activePlayerCount"] == 6
        shares = [Decimal(value) for value in multiway["equityBySeat"].values()]
        assert abs(sum(shares) - Decimal("1")) < Decimal("1e-9")
        assert set(multiway["equityBySeat"]) == {"0", "1", "2", "3", "4", "5"}
        # The per-seat evidence item is present and traceable.
        evidence = analysis["evidence"]["items"]
        assert any(item["evidenceId"] == "equity.multiway_by_seat" for item in evidence)
        assert analysis["warnings"] == []

    def test_multiway_pot_odds_over_live_players(self):
        client = TestClient(create_app())
        scenario = api_scenario(
            6,
            heroSeat=2,
            knownHoleCardsBySeat={
                0: ["As", "Kd"],
                1: ["Qh", "Qc"],
                2: ["7c", "7h"],
                3: ["8c", "8h"],
                4: ["5c", "5h"],
            },
            actionHistory=[
                action(1, 3, "raise_to", amount=300, amount_type="to"),
                action(2, 4, "call", amount=300, amount_type="cost"),
                action(3, 5, "fold"),
                action(4, 0, "fold"),
                action(5, 1, "fold"),
            ],
            decisionPoint={"street": "preflop", "actorSeat": 2, "afterSequence": 5},
        )
        response = client.post("/v1/analysis", json=scenario.to_dict())
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        metrics = analysis["metrics"]
        # Live players: hero (BB), UTG, MP. Hero faces 200 into a 950 pot.
        assert metrics["activePlayerCount"] == 3
        assert metrics["callCost"] == 200
        assert metrics["potAfterCall"] == 950
        assert metrics["potOdds"] == str(Decimal(200) / Decimal(950))
        multiway = analysis["multiwayEquity"]
        assert multiway["activePlayerCount"] == 3
        assert set(multiway["equityBySeat"]) == {"2", "3", "4"}

    def test_missing_opponent_cards_degrades_to_warning(self):
        client = TestClient(create_app())
        scenario = api_scenario(
            6,
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"]},
            decisionPoint={"street": "preflop", "actorSeat": 3, "afterSequence": 0},
        )
        response = client.post("/v1/analysis", json=scenario.to_dict())
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        assert analysis["multiwayEquity"] is None
        assert any("multiway equity is unavailable" in warning for warning in analysis["warnings"])

    def test_folded_players_do_not_count_as_active(self):
        client = TestClient(create_app())
        scenario = api_scenario(
            6,
            heroSeat=2,
            knownHoleCardsBySeat={
                0: ["As", "Kd"],
                1: ["Qh", "Qc"],
                2: ["7c", "7h"],
                3: ["8c", "8h"],
                4: ["5c", "5h"],
            },
            actionHistory=[
                action(1, 3, "fold"),
                action(2, 4, "fold"),
                action(3, 5, "fold"),
                action(4, 0, "fold"),
            ],
            decisionPoint={"street": "preflop", "actorSeat": 1, "afterSequence": 4},
        )
        response = client.post("/v1/analysis", json=scenario.to_dict())
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        assert analysis["metrics"]["activePlayerCount"] == 2
        multiway = analysis["multiwayEquity"]
        assert multiway is not None
        assert multiway["activePlayerCount"] == 2
        assert set(multiway["equityBySeat"]) == {"1", "2"}

    def test_hu_analysis_still_uses_the_hero_villain_shape(self):
        client = TestClient(create_app())
        scenario = multiway_scenario(
            2,
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Qc"]},
            board=["2c", "7d", "Jh", "9s", "3h"],
            actionHistory=[
                action(1, 0, "raise_to", amount=300, amount_type="to"),
                action(2, 1, "call", amount=200, amount_type="cost"),
                action(3, 1, "deal_flop", street="flop"),
                action(4, 1, "check", street="flop"),
                action(5, 0, "check", street="flop"),
                action(6, 1, "deal_turn", street="turn"),
                action(7, 1, "check", street="turn"),
                action(8, 0, "check", street="turn"),
                action(9, 1, "deal_river", street="river"),
                action(10, 1, "check", street="river"),
                action(11, 0, "check", street="river"),
                action(12, 0, "showdown", street="showdown"),
            ],
            decisionPoint={"street": "showdown", "actorSeat": 0, "afterSequence": 12},
        )
        response = client.post("/v1/analysis", json=scenario.to_dict())
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        # Heads-up keeps the legacy hero/villain equity shape.
        assert analysis["equity"] is not None
        assert analysis["multiwayEquity"] is None
        assert analysis["metrics"]["activePlayerCount"] == 2
