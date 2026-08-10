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
    payload = {"scenario": SCENARIO}
    response = app_client.post("/v1/solve/jobs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


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
