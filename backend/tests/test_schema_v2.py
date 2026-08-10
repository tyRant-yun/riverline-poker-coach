"""Phase 8A: schema v2 — seat-based scenarios, position derivation, migration.

Covers the generalized 2-8 seat schema, knownHoleCardsBySeat/rangesBySeat
normalization, and the honest boundaries (multiway replay/solver guards).
"""

import pytest
from pydantic import ValidationError

from poker_coach.domain.models import (
    SCENARIO_SCHEMA_VERSION,
    SeatPosition,
    ScenarioSpec,
    derive_position,
    positions_for_table,
)
from poker_coach.rules import PokerKitAdapter
from poker_coach.solver.adapter import SolverUnsupportedError, build_spot


def v2_scenario(table_size, *, button_seat=0, hero_seat=0, **overrides):
    positions = [p.value for p in positions_for_table(table_size)]
    seats = [
        {
            "seatId": seat_id,
            "startingStack": 10_000,
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


class TestPositionDerivation:
    def test_hu_positions_are_button_and_big_blind(self):
        assert derive_position(2, 0, 0) is SeatPosition.BUTTON
        assert derive_position(2, 0, 1) is SeatPosition.BIG_BLIND
        assert derive_position(2, 1, 1) is SeatPosition.BUTTON
        assert derive_position(2, 1, 0) is SeatPosition.BIG_BLIND

    def test_short_handed_positions(self):
        assert derive_position(3, 0, 1) is SeatPosition.SMALL_BLIND
        assert derive_position(4, 0, 3) is SeatPosition.CUTOFF
        assert derive_position(5, 0, 3) is SeatPosition.UTG

    def test_8max_positions_follow_the_standard_set(self):
        expected = [
            "button",
            "small_blind",
            "big_blind",
            "utg",
            "utg+1",
            "mp",
            "hj",
            "co",
        ]
        for seat_id, position in enumerate(expected):
            assert derive_position(8, 0, seat_id).value == position

    def test_rotation_keeps_derivation_consistent(self):
        # Button on seat 3: offsets rotate identically.
        assert derive_position(6, 3, 3) is SeatPosition.BUTTON
        assert derive_position(6, 3, 4) is SeatPosition.SMALL_BLIND
        assert derive_position(6, 3, 5) is SeatPosition.BIG_BLIND
        assert derive_position(6, 3, 2) is SeatPosition.CUTOFF

    def test_unsupported_table_size_raises(self):
        with pytest.raises(ValueError, match="unsupported table_size"):
            positions_for_table(9)


class TestSchemaV2:
    def test_v2_known_hole_cards_normalize_to_legacy_views(self):
        scenario = v2_scenario(
            2,
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Jc"]},
        )
        assert scenario.hero_hole_cards == ("Kd", "As")
        assert scenario.villain_hole_cards == ("Jc", "Qh")
        assert scenario.known_hole_cards_by_seat == {0: ("Kd", "As"), 1: ("Jc", "Qh")}

    def test_v2_ranges_by_seat_normalize_to_legacy_views(self):
        hero_range = {
            "rangeId": "h",
            "name": "hero",
            "version": "1",
            "source": "user_defined",
            "matrix169": {"22": "1"},
        }
        villain_range = {
            "rangeId": "v",
            "name": "villain",
            "version": "1",
            "source": "user_defined",
            "matrix169": {"33": "1"},
        }
        scenario = v2_scenario(2, rangesBySeat={0: hero_range, 1: villain_range})
        assert scenario.hero_range is not None and scenario.hero_range.range_id == "h"
        assert scenario.villain_range is not None and scenario.villain_range.range_id == "v"
        assert set(scenario.ranges_by_seat) == {0, 1}

    def test_v1_payloads_are_normalized_into_seat_fields(self):
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
                    {"seatId": 0, "startingStack": 10_000, "position": "button"},
                    {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
                ],
                "heroHoleCards": ["As", "Kd"],
                "villainHoleCards": ["Qh", "Jc"],
                "board": [],
                "actionHistory": [],
                "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
                "assumptions": {},
            }
        )
        assert scenario.known_hole_cards_by_seat == {0: ("Kd", "As"), 1: ("Jc", "Qh")}

    def test_6max_and_8max_scenarios_validate(self):
        six = v2_scenario(6)
        assert len(six.seats) == 6
        eight = v2_scenario(8)
        assert len(eight.seats) == 8
        assert {seat.position.value for seat in eight.seats} == {
            "button",
            "small_blind",
            "big_blind",
            "utg",
            "utg+1",
            "mp",
            "hj",
            "co",
        }

    def test_8max_seat_ids_0_to_7_accepted_8_rejected(self):
        v2_scenario(8)  # seats 0..7 accepted
        with pytest.raises(ValidationError):
            v2_scenario(8, seats=[{"seatId": 8, "startingStack": 10_000, "position": "co"}] + [
                {"seatId": i, "startingStack": 10_000, "position": "button" if i == 0 else "small_blind"}
                for i in range(7)
            ])

    def test_position_declared_against_derivation_is_rejected(self):
        with pytest.raises(ValidationError, match="position must be big_blind"):
            v2_scenario(
                2,
                seats=[
                    {"seatId": 0, "startingStack": 10_000, "position": "button"},
                    {"seatId": 1, "startingStack": 10_000, "position": "small_blind"},
                ],
            )

    def test_table_size_beyond_8_rejected(self):
        positions = ["button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co"]
        payload = {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": 9,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": seat_id, "startingStack": 10_000, "position": positions[seat_id % 8]}
                for seat_id in range(9)
            ],
            "knownHoleCardsBySeat": {0: ["As", "Kd"]},
            "board": [],
            "actionHistory": [],
            "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
            "assumptions": {},
        }
        with pytest.raises(ValidationError):
            ScenarioSpec.model_validate(payload)

    def test_v2_requires_hero_hole_cards(self):
        with pytest.raises(ValidationError, match="must include the hero seat"):
            v2_scenario(2, knownHoleCardsBySeat={1: ["Qh", "Jc"]})

    def test_known_cards_must_reference_existing_seats(self):
        with pytest.raises(ValidationError, match="must reference existing seats"):
            v2_scenario(2, knownHoleCardsBySeat={0: ["As", "Kd"], 5: ["Qh", "Jc"]})

    def test_multiway_known_cards_do_not_create_villain(self):
        scenario = v2_scenario(6, knownHoleCardsBySeat={0: ["As", "Kd"], 3: ["Qh", "Jc"]})
        assert scenario.villain_hole_cards is None  # no single villain in 6-max
        assert scenario.hero_hole_cards == ("Kd", "As")

    def test_v2_range_overlap_with_known_cards_rejected(self):
        with pytest.raises(ValidationError, match="contains a known card"):
            v2_scenario(
                2,
                rangesBySeat={
                    1: {
                        "rangeId": "v",
                        "name": "v",
                        "version": "1",
                        "source": "user_defined",
                        "combos": [{"cards": ["As", "Qd"], "weight": "1"}],
                    }
                },
            )

    def test_round_trip_is_deterministic_for_v2(self):
        scenario = v2_scenario(6, rangesBySeat={})
        assert scenario.to_json() == ScenarioSpec.from_json(scenario.to_json()).to_json()


class TestHonestBoundaries:
    def test_8max_scenario_replays_without_a_hero_villain_pair(self):
        # Phase 8B: multiway replay works; no single villain is required.
        scenario = v2_scenario(8)
        result = PokerKitAdapter().replay(scenario)
        state = result.final_state
        assert len(state.stacks) == 8
        assert state.hand_in_progress is True
        assert state.pot == 150  # blinds posted
        # Preflop first actor is UTG (seat 3 with button on seat 0).
        assert state.actor_seat == 3
        assert set(state.legal_actions.actions) == {"raise_to", "fold", "call", "all_in"}

    def test_multiway_solver_spot_is_unsupported(self):
        # A flop with three live players is not a heads-up decision point.
        scenario = v2_scenario(
            6,
            heroSeat=2,
            knownHoleCardsBySeat={2: ["As", "Kd"]},
            board=["2c", "7d", "Jh"],
            actionHistory=[
                {"actionId": "a1", "sequence": 1, "street": "preflop", "actorSeat": 3, "actionType": "raise_to", "amount": 300, "amountType": "to"},
                {"actionId": "a2", "sequence": 2, "street": "preflop", "actorSeat": 4, "actionType": "call", "amount": 300, "amountType": "cost"},
                {"actionId": "a3", "sequence": 3, "street": "preflop", "actorSeat": 5, "actionType": "fold"},
                {"actionId": "a4", "sequence": 4, "street": "preflop", "actorSeat": 0, "actionType": "fold"},
                {"actionId": "a5", "sequence": 5, "street": "preflop", "actorSeat": 1, "actionType": "fold"},
                {"actionId": "a6", "sequence": 6, "street": "preflop", "actorSeat": 2, "actionType": "call", "amount": 200, "amountType": "cost"},
                {"actionId": "a7", "sequence": 7, "street": "flop", "actorSeat": 1, "actionType": "deal_flop"},
            ],
            decisionPoint={"street": "flop", "actorSeat": 2, "afterSequence": 7},
        )
        with pytest.raises(SolverUnsupportedError, match="heads-up"):
            build_spot(scenario)

    def test_hu_solver_spot_still_builds(self):
        scenario = v2_scenario(
            2,
            board=["2c", "7d", "Jh"],
            actionHistory=[
                {
                    "actionId": "c1",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "c2",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "d1",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 1,
                    "actionType": "deal_flop",
                },
            ],
            decisionPoint={"street": "flop", "actorSeat": 1, "afterSequence": 3},
            rangesBySeat={
                0: {
                    "rangeId": "h",
                    "name": "hero",
                    "version": "1",
                    "source": "user_defined",
                    "matrix169": {"22": "1"},
                },
                1: {
                    "rangeId": "v",
                    "name": "villain",
                    "version": "1",
                    "source": "user_defined",
                    "matrix169": {"33": "1"},
                },
            },
        )
        spot = build_spot(scenario)
        assert spot is not None
        assert spot.board == ("2c", "7d", "Jh")

    def test_schema_version_constant_is_v2(self):
        assert SCENARIO_SCHEMA_VERSION == 2


class TestApiContract:
    def test_validate_accepts_v2_hu_scenario(self):
        from fastapi.testclient import TestClient

        from poker_coach.api import create_app

        client = TestClient(create_app())
        payload = v2_scenario(
            2,
            knownHoleCardsBySeat={0: ["As", "Kd"], 1: ["Qh", "Jc"]},
        ).to_dict()
        response = client.post("/v1/scenarios/validate", json=payload)
        assert response.status_code == 200
        normalized = response.json()["normalizedScenario"]
        assert normalized["schemaVersion"] == 2
        assert normalized["knownHoleCardsBySeat"]["0"] == ["Kd", "As"]

    def test_validate_accepts_multiway_scenario(self):
        from fastapi.testclient import TestClient

        from poker_coach.api import create_app

        client = TestClient(create_app())
        payload = v2_scenario(
            8,
            decisionPoint={"street": "preflop", "actorSeat": 3, "afterSequence": 0},
        ).to_dict()
        response = client.post("/v1/scenarios/validate", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert len(body["finalState"]["stacks"]) == 8
        assert body["finalState"]["actorSeat"] == 3

    def test_solve_jobs_reject_multiway_spot(self):
        from fastapi.testclient import TestClient

        from poker_coach.api import create_app

        client = TestClient(create_app())
        payload = v2_scenario(
            6,
            heroSeat=2,
            knownHoleCardsBySeat={2: ["As", "Kd"]},
            board=["2c", "7d", "Jh"],
            actionHistory=[
                {"actionId": "a1", "sequence": 1, "street": "preflop", "actorSeat": 3, "actionType": "raise_to", "amount": 300, "amountType": "to"},
                {"actionId": "a2", "sequence": 2, "street": "preflop", "actorSeat": 4, "actionType": "call", "amount": 300, "amountType": "cost"},
                {"actionId": "a3", "sequence": 3, "street": "preflop", "actorSeat": 5, "actionType": "fold"},
                {"actionId": "a4", "sequence": 4, "street": "preflop", "actorSeat": 0, "actionType": "fold"},
                {"actionId": "a5", "sequence": 5, "street": "preflop", "actorSeat": 1, "actionType": "fold"},
                {"actionId": "a6", "sequence": 6, "street": "preflop", "actorSeat": 2, "actionType": "call", "amount": 200, "amountType": "cost"},
                {"actionId": "a7", "sequence": 7, "street": "flop", "actorSeat": 1, "actionType": "deal_flop"},
            ],
            decisionPoint={"street": "flop", "actorSeat": 2, "afterSequence": 7},
        ).to_dict()
        response = client.post(
            "/v1/solve/jobs",
            json={
                "scenario": payload,
                "heroRange": {"rangeId": "h", "name": "h", "version": "1", "source": "user_defined", "matrix169": {"22": "1"}},
                "villainRange": {"rangeId": "v", "name": "v", "version": "1", "source": "user_defined", "matrix169": {"33": "1"}},
            },
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_spot"
        assert "heads-up" in error["message"]
