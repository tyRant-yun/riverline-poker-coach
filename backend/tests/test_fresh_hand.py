"""A brand-new hand: 0 inputs, 0 actions — only the blinds are posted.

The hero has no hole cards yet (the user fills them in afterwards), which is
a legitimate scenario: replay works, the pot is the two blinds, and analysis
degrades honestly instead of crashing.
"""

from fastapi.testclient import TestClient

from poker_coach.analysis import analyze_scenario
from poker_coach.api import create_app
from poker_coach.domain.models import ScenarioSpec, Street
from poker_coach.rules import PokerKitAdapter


def fresh_hand_payload():
    return {
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
        "board": [],
        "actionHistory": [],
        "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
        "assumptions": {},
    }


class TestFreshHandReplay:
    def test_blinds_only_state(self):
        scenario = ScenarioSpec.model_validate(fresh_hand_payload())
        assert scenario.hero_hole_cards is None

        result = PokerKitAdapter().replay(scenario)
        state = result.final_state
        assert state.street is Street.PREFLOP
        assert state.pot == 150  # small blind 50 + big blind 100
        assert state.actor_seat == 0  # button acts first preflop
        assert "call" in state.legal_actions.actions
        assert "raise_to" in state.legal_actions.actions
        assert "fold" in state.legal_actions.actions
        assert state.stacks == {0: 9950, 1: 9900}

    def test_fill_hero_cards_then_act(self):
        # The user fills hero cards in afterwards; the hand proceeds normally.
        payload = fresh_hand_payload()
        payload["heroHoleCards"] = ["As", "Kd"]
        payload["actionHistory"] = [
            {"actionId": "a1", "sequence": 1, "street": "preflop", "actorSeat": 0, "actionType": "call", "amount": 50, "amountType": "cost"},
        ]
        payload["decisionPoint"] = {"street": "preflop", "actorSeat": 1, "afterSequence": 1}
        scenario = ScenarioSpec.model_validate(payload)
        result = PokerKitAdapter().replay_to_decision(scenario)
        assert result.final_state.pot == 200
        assert result.final_state.actor_seat == 1
        assert "check" in result.final_state.legal_actions.actions


class TestFreshHandAnalysis:
    def test_analysis_degrades_without_hero_cards(self):
        scenario = ScenarioSpec.model_validate(fresh_hand_payload())
        result = analyze_scenario(scenario)
        assert result.hand is None
        assert result.equity is None
        assert any("hero hole cards are missing" in warning for warning in result.warnings)
        assert result.metrics.current_pot == 150

    def test_analysis_fills_in_after_hero_cards(self):
        payload = fresh_hand_payload()
        payload["heroHoleCards"] = ["As", "Kd"]
        scenario = ScenarioSpec.model_validate(payload)
        result = analyze_scenario(scenario)
        assert result.hand is not None
        assert result.hand.category == "high_card"


class TestFreshHandApi:
    def test_state_endpoint_accepts_a_fresh_hand(self):
        client = TestClient(create_app())
        response = client.post("/v1/scenarios/state", json=fresh_hand_payload())
        assert response.status_code == 200
        snapshots = response.json()["snapshots"]
        assert snapshots[-1]["pot"] == 150
        assert snapshots[-1]["street"] == "preflop"

    def test_validate_endpoint_accepts_a_fresh_hand(self):
        client = TestClient(create_app())
        response = client.post("/v1/scenarios/validate", json=fresh_hand_payload())
        assert response.status_code == 200
        assert response.json()["valid"] is True
