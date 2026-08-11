"""API tests for the range belief endpoints (/v1/ranges/belief, /v1/ranges/trace)."""

from __future__ import annotations

from decimal import Decimal

import pytest
import fakeredis
from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence.sqlite_store import SQLiteStore
from poker_coach.solver import SolverJobQueue
from poker_coach.solver.adapter import parse_result

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PRIOR_MATRIX = {"AA": "1", "KK": "1", "76s": "1", "J4o": "0.2"}


def belief_scenario_payload(*, actions: int = 1) -> dict:
    """HU scenario: BTN raise (seq 1), BB call (seq 2), flop dealt."""
    events = [
        {
            "actionId": "open",
            "sequence": 1,
            "street": "preflop",
            "actorSeat": 0,
            "actionType": "raise_to",
            "amount": 250,
            "amountType": "to",
        },
        {
            "actionId": "call",
            "sequence": 2,
            "street": "preflop",
            "actorSeat": 1,
            "actionType": "call",
            "amount": 150,
            "amountType": "cost",
        },
        {
            "actionId": "flop",
            "sequence": 3,
            "street": "flop",
            "actorSeat": 0,
            "actionType": "deal_flop",
        },
    ]
    if actions >= 4:
        events.append(
            {
                "actionId": "bet",
                "sequence": 4,
                "street": "flop",
                "actorSeat": 1,
                "actionType": "bet",
                "amount": 100,
                "amountType": "by",
            }
        )
    after = 4 if actions >= 4 else 3
    # After BB's flop bet (seq 4) the BTN acts; after the flop deal the BB acts.
    actor_seat = 0 if actions >= 4 else 1
    return {
        "schemaVersion": 1,
        "gameVariant": "nlhe",
        "tableSize": 2,
        "smallBlind": 50,
        "bigBlind": 100,
        "buttonSeat": 0,
        "heroSeat": 0,
        "seats": [
            {"seatId": 0, "startingStack": 10000, "position": "button"},
            {"seatId": 1, "startingStack": 10000, "position": "big_blind"},
        ],
        "board": ["Ks", "7d", "2c"],
        "actionHistory": events,
        "decisionPoint": {"street": "flop", "actorSeat": actor_seat, "afterSequence": after},
        "assumptions": {},
        "rangesBySeat": {
            "0": {
                "rangeId": "prior-0",
                "name": "BTN prior",
                "version": "1",
                "source": "user_defined",
                "matrix169": PRIOR_MATRIX,
            },
            "1": {
                "rangeId": "prior-1",
                "name": "BB prior",
                "version": "1",
                "source": "user_defined",
                "matrix169": PRIOR_MATRIX,
            },
        },
    }


def fixture_policy_payload() -> dict:
    return {
        "source": "fixture",
        "frequencies": {
            "raise_to": {
                "AA": {"raise": "1"},
                "KK": {"raise": "0.8"},
                "76s": {"raise": "0.7"},
                "J4o": {"raise": "0.05"},
            }
        },
    }


def eight_max_rfi_payload() -> dict:
    positions = ("button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co")
    return {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": 8,
        "smallBlind": 50,
        "bigBlind": 100,
        "buttonSeat": 0,
        "heroSeat": 3,
        "seats": [
            {"seatId": seat_id, "startingStack": 10000, "position": position}
            for seat_id, position in enumerate(positions)
        ],
        "board": [],
        "actionHistory": [
            {
                "actionId": "utg-open",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 3,
                "actionType": "raise_to",
                "amount": 250,
                "amountType": "to",
            }
        ],
        "decisionPoint": {"street": "preflop", "actorSeat": 4, "afterSequence": 1},
        "assumptions": {},
        "rangesBySeat": {
            "3": {
                "rangeId": "utg-prior",
                "name": "UTG prior",
                "version": "1",
                "source": "user_defined",
                "matrix169": {"AA": "1", "A5s": "1"},
            }
        },
    }


def solver_result_payload() -> dict:
    return {
        "metadata": {
            "solver": "postflop-solver",
            "version": "test",
            "street": "flop",
            "maxIterations": 1,
            "exploitabilityChips": 0.0,
            "targetExploitabilityChips": 0.0,
        },
        "root": {
            "actions": ["Check", "Bet(100)"],
            "player": 0,
            "hands": [
                {
                    "combo": "AsKs",
                    "weight": 1.0,
                    "equity": 0.5,
                    "ev": 0.1,
                    "strategy": {"Check": 0.7, "Bet(100)": 0.3},
                },
                {
                    "combo": "AhKh",
                    "weight": 1.0,
                    "equity": 0.5,
                    "ev": 0.2,
                    "strategy": {"Check": 0.2, "Bet(100)": 0.8},
                },
            ],
        },
        "responseNode": None,
    }


def test_belief_with_fixture_policy_returns_current_and_matrix():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={"scenario": belief_scenario_payload(), "seatId": 0, "policy": fixture_policy_payload()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert payload["seatId"] == 0
    assert payload["source"] == "fixture"
    assert payload["confidence"] == "grounded"
    assert payload["afterSequence"] == 3
    # The last transition is the flop deal; the raise updated the belief at
    # seq 1 (visible in the combo probabilities).
    assert payload["update"]["actionType"] == "deal_flop"
    assert payload["combos"]["AsAh"]["priorProbability"] != payload["combos"]["AsAh"]["probability"]
    assert payload["matrix169"]["AA"]["comboCount"] == 6
    # The AA cell sums the mass of its 6 concrete combos (all raised at 1.0);
    # Decimal double-rounding allows a tiny tolerance.
    assert abs(
        Decimal(payload["matrix169"]["AA"]["probabilityMass"])
        - Decimal("6") * Decimal(payload["combos"]["AsAh"]["probability"])
    ) < Decimal("1e-24")
    total = sum(Decimal(cell["probabilityMass"]) for cell in payload["matrix169"].values())
    assert abs(total - Decimal("1")) < Decimal("1e-9")


def test_belief_without_policy_is_unavailable_and_honest():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={"scenario": belief_scenario_payload(), "seatId": 0},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is False
    assert "no_policy" in payload["unavailableReason"]
    assert payload["combos"] is not None  # prior combos still visible
    assert payload["matrix169"] is not None


def test_belief_with_builtin_8max_preflop_policy_is_curated_and_exact_node_only():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": eight_max_rfi_payload(),
            "seatId": 3,
            "policy": {"source": "preflop_policy"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert payload["source"] == "preflop_policy"
    assert payload["confidence"] == "curated"
    assert payload["update"]["actionLabel"] == "Raise(250)"
    assert payload["update"]["node"].endswith("8max-rfi-utg-2.5bb")
    # The view intentionally unions prior/current cells, so the folded A5s
    # cell remains visible with zero current mass and a negative delta.
    assert Decimal(payload["matrix169"]["AA"]["probabilityMass"]) == Decimal("1")
    assert Decimal(payload["matrix169"]["A5s"]["probabilityMass"]) == Decimal("0")


def test_builtin_preflop_policy_rejects_unrecognized_extra_fields():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": eight_max_rfi_payload(),
            "seatId": 3,
            "policy": {"source": "preflop_policy", "version": "anything"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_policy"


def test_belief_with_solver_result_policy():
    client = TestClient(create_app())
    scenario = belief_scenario_payload(actions=4)
    scenario["rangesBySeat"]["1"]["matrix169"] = {"AKs": "1"}
    # Board without a K so both solver combos (AsKs, AhKh) survive the deal.
    scenario["board"] = ["Qs", "7d", "2c"]
    # Provider chain: a fixture covers the tracked seat's preflop call
    # (reach unchanged), then the solver adapter covers the flop bet.
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": scenario,
            "seatId": 1,
            "policy": [
                {"source": "fixture", "frequencies": {"call": {"AKs": {"call": "1"}}}},
                {"source": "solver", "result": solver_result_payload()},
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert payload["source"] == "solver"
    assert payload["afterSequence"] == 4
    assert payload["update"]["actionType"] == "bet"
    assert payload["update"]["offTree"] is False  # Bet(100) == 20% of pot 500
    assert payload["combos"]["AhKh"]["probability"] > payload["combos"]["AsKs"]["probability"]


def test_belief_with_solver_result_at_preflop_is_invalid_policy():
    client = TestClient(create_app())
    scenario = belief_scenario_payload()
    scenario["decisionPoint"] = {"street": "preflop", "actorSeat": 0, "afterSequence": 0}
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": scenario,
            "seatId": 0,
            "policy": {"source": "solver", "result": solver_result_payload()},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_policy"


def test_belief_with_solver_job_requires_and_verifies_exact_node_provenance():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    app = create_app(
        config=AppConfig(),
        store=SQLiteStore(":memory:"),
        solver_queue=queue,
    )
    client = TestClient(app)
    try:
        before_action = belief_scenario_payload()
        before_action["board"] = ["Qs", "7d", "2c"]
        before_action["rangesBySeat"]["1"]["matrix169"] = {"AKs": "1"}
        submitted = client.post("/v1/solve/jobs", json={"scenario": before_action})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(
            job_id,
            status="solved",
            result=parse_result(solver_result_payload()),
        )

        after_action = belief_scenario_payload(actions=4)
        after_action["board"] = ["Qs", "7d", "2c"]
        after_action["rangesBySeat"]["1"]["matrix169"] = {"AKs": "1"}
        response = client.post(
            "/v1/ranges/belief",
            json={
                "scenario": after_action,
                "seatId": 1,
                "policy": [
                    {"source": "fixture", "frequencies": {"call": {"AKs": {"call": "1"}}}},
                    {"source": "solver", "jobId": job_id},
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["confidence"] == "grounded"
        assert response.json()["update"]["actionType"] == "bet"

        wrong_scenario = {**after_action, "board": ["Qh", "8h", "3s"]}
        mismatch = client.post(
            "/v1/ranges/belief",
            json={
                "scenario": wrong_scenario,
                "seatId": 1,
                "policy": {"source": "solver", "jobId": job_id},
            },
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["error"]["code"] == "solver_artifact_mismatch"
    finally:
        queue.close()


def test_raw_solver_result_is_explicitly_unverified_compatibility_input():
    client = TestClient(create_app())
    scenario = belief_scenario_payload(actions=4)
    scenario["rangesBySeat"]["1"]["matrix169"] = {"AKs": "1"}
    scenario["board"] = ["Qs", "7d", "2c"]
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": scenario,
            "seatId": 1,
            "policy": [
                {"source": "fixture", "frequencies": {"call": {"AKs": {"call": "1"}}}},
                {"source": "solver", "result": solver_result_payload()},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["confidence"] == "unverified"


def test_trace_returns_snapshot_chain():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/trace",
        json={"scenario": belief_scenario_payload(), "seatId": 0, "policy": fixture_policy_payload()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert [snapshot["afterSequence"] for snapshot in payload["snapshots"]] == [0, 1, 3]
    assert payload["snapshots"][0]["source"] == "manual"
    assert payload["snapshots"][1]["parentSnapshotId"] == payload["snapshots"][0]["snapshotId"]


def test_belief_without_prior_range_is_422():
    client = TestClient(create_app())
    scenario = belief_scenario_payload()
    scenario.pop("rangesBySeat")
    response = client.post(
        "/v1/ranges/belief",
        json={"scenario": scenario, "seatId": 0},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_prior_range"


def test_belief_invalid_seat_is_422():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={"scenario": belief_scenario_payload(), "seatId": 9},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_belief_invalid_policy_source_is_422():
    client = TestClient(create_app())
    response = client.post(
        "/v1/ranges/belief",
        json={
            "scenario": belief_scenario_payload(),
            "seatId": 0,
            "policy": {"source": "llm"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_policy"
