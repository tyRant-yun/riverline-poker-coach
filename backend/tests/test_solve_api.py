"""Solve job API tests: submit/query/cancel over an injected in-memory queue."""

from __future__ import annotations

import json
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence.sqlite_store import SQLiteStore
from poker_coach.solver import SolverJobQueue

FIXTURE = Path(__file__).parent / "fixtures" / "solve-output-spike1.json"


def _range_payload(*combos: tuple[tuple[str, str], float]) -> dict:
    return {
        "rangeId": "api-test",
        "name": "api test",
        "version": "1",
        "source": "user_defined",
        "combos": [
            {"cards": sorted(cards, key=lambda c: "23456789TJQKA".index(c[0])), "weight": weight}
            for cards, weight in combos
        ],
    }


SCENARIO = {
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
    "heroHoleCards": ["Ac", "Kc"],
    "villainHoleCards": None,
    "board": ["Ks", "7h", "2h"],
    "actionHistory": [
        {"actionId": "open", "sequence": 1, "street": "preflop", "actorSeat": 0, "actionType": "raise_to", "amount": 250, "amountType": "to"},
        {"actionId": "call", "sequence": 2, "street": "preflop", "actorSeat": 1, "actionType": "call", "amount": 150, "amountType": "cost"},
        {"actionId": "flop", "sequence": 3, "street": "flop", "actorSeat": 0, "actionType": "deal_flop"},
    ],
    "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
    "assumptions": {},
    "source": "manual",
    "tags": ["solve-api-test"],
}


@pytest.fixture()
def app_client():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    app = create_app(
        config=AppConfig(),
        store=SQLiteStore(":memory:"),
        solver_queue=queue,
    )
    yield TestClient(app)
    queue.close()


def test_solve_job_submit_query_cancel(app_client):
    payload = {
        "scenario": SCENARIO,
        "heroRange": _range_payload((["Kc", "Ac"], 1)),
        "villainRange": _range_payload((["Qc", "Qh"], 1)),
        "maxIterations": 50,
    }
    submitted = app_client.post("/v1/solve/jobs", json=payload)
    assert submitted.status_code == 202
    body = submitted.json()
    assert body["status"] == "queued"
    job_id = body["jobId"]
    assert body["spot"]["startingPot"] == 500
    assert body["spot"]["effectiveStack"] == 9750
    assert "Ks" in body["spot"]["board"]

    status = app_client.get(f"/v1/solve/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"

    cancelled = app_client.post(f"/v1/solve/jobs/{job_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"

    after = app_client.get(f"/v1/solve/jobs/{job_id}")
    assert after.json()["status"] == "cancelled"


def test_solve_job_requires_ranges(app_client):
    # A spot whose active seats have no ranges anywhere is still rejected —
    # but with the structured unsupported-spot error, not a legacy
    # heroRange/villainRange requirement.
    payload = {"scenario": SCENARIO}
    response = app_client.post("/v1/solve/jobs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_spot"
    assert "ranges for the active seats" in response.json()["error"]["message"]


def test_solve_job_rejects_preflop(app_client):
    preflop = dict(SCENARIO)
    preflop["decisionPoint"] = {"street": "preflop", "actorSeat": 0, "afterSequence": 2}
    payload = {
        "scenario": preflop,
        "heroRange": _range_payload((["Kc", "Ac"], 1)),
        "villainRange": _range_payload((["Qc", "Qh"], 1)),
    }
    response = app_client.post("/v1/solve/jobs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_spot"


def test_solve_job_unavailable_without_queue():
    app = create_app(config=AppConfig(), store=SQLiteStore(":memory:"))
    client = TestClient(app)
    payload = {
        "scenario": SCENARIO,
        "heroRange": _range_payload((["Kc", "Ac"], 1)),
        "villainRange": _range_payload((["Qc", "Qh"], 1)),
    }
    response = client.post("/v1/solve/jobs", json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "solver_unavailable"


def _range_matrix_payload(range_id: str, entry: str) -> dict:
    return {
        "rangeId": range_id,
        "name": range_id,
        "version": "1",
        "source": "user_defined",
        "matrix169": {entry: "1"},
    }


def _v2_bridge_scenario() -> dict:
    """6-max Schema v2 spot: only BTN (0) and BB (2) live at the flop.

    Hero is seat 4 — a folded preflop player, proving the solver resolves
    ranges from the active seats rather than the Coach's hero view. A
    folded short stack (seat 1, 2000) must not affect the effective stack.
    """
    positions = ["button", "small_blind", "big_blind", "utg", "mp", "co"]
    return {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": 6,
        "smallBlind": 50,
        "bigBlind": 100,
        "ante": 0,
        "buttonSeat": 0,
        "heroSeat": 4,
        "seats": [
            {"seatId": seat_id, "startingStack": stack, "position": positions[seat_id]}
            for seat_id, stack in enumerate([8_000, 2_000, 9_000, 5_000, 10_000, 10_000])
        ],
        "knownHoleCardsBySeat": {"4": ["As", "Kd"]},
        "board": ["2c", "7d", "Jh"],
        "actionHistory": [
            {"actionId": "a1", "sequence": 1, "street": "preflop", "actorSeat": 3, "actionType": "fold"},
            {"actionId": "a2", "sequence": 2, "street": "preflop", "actorSeat": 4, "actionType": "fold"},
            {"actionId": "a3", "sequence": 3, "street": "preflop", "actorSeat": 5, "actionType": "fold"},
            {"actionId": "a4", "sequence": 4, "street": "preflop", "actorSeat": 0, "actionType": "raise_to", "amount": 300, "amountType": "to"},
            {"actionId": "a5", "sequence": 5, "street": "preflop", "actorSeat": 1, "actionType": "fold"},
            {"actionId": "a6", "sequence": 6, "street": "preflop", "actorSeat": 2, "actionType": "call", "amount": 200, "amountType": "cost"},
            {"actionId": "a7", "sequence": 7, "street": "flop", "actorSeat": 1, "actionType": "deal_flop"},
        ],
        "decisionPoint": {"street": "flop", "actorSeat": 2, "afterSequence": 7},
        "assumptions": {},
        "rangesBySeat": {
            "0": _range_matrix_payload("btn", "99"),
            "2": _range_matrix_payload("bb", "22"),
        },
        "source": "manual",
        "tags": ["solve-schema-v2"],
    }


def test_solve_job_schema_v2_ranges_by_seat_only(app_client):
    """A Schema v2 multiway-origin spot reaches the HU solver through the
    real API path with rangesBySeat alone (no heroRange/villainRange)."""
    payload = {
        "scenario": _v2_bridge_scenario(),
        "maxIterations": 50,
    }
    submitted = app_client.post("/v1/solve/jobs", json=payload)
    assert submitted.status_code == 202
    body = submitted.json()
    assert body["status"] == "queued"
    spot = body["spot"]
    # OOP = BB (seat 2), IP = BTN (seat 0), resolved from the active seats.
    assert spot["oopRange"] == "22:1"
    assert spot["ipRange"] == "99:1"
    # Active stacks: BTN 7700 (8000-300), BB 8800 (9000-200); the folded
    # 1950 SB stack does not drag the spot down.
    assert spot["effectiveStack"] == 7700
    assert spot["startingPot"] == 650
    # The multiway-origin spot records the bunching approximation.
    assert spot["assumptions"] == ["bunching_ignored"]

    job_id = body["jobId"]
    status = app_client.get(f"/v1/solve/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
