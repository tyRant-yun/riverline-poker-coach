from fastapi.testclient import TestClient
import pytest

from poker_coach.api import create_app
from poker_coach.persistence import SQLiteStore

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def scenario_payload():
    return {
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
        "board": ["2c", "7d", "Jh"],
        "actionHistory": [
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
        ],
        "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
        "assumptions": {},
    }


def test_health_and_version_include_request_id():
    client = TestClient(create_app())
    response = client.get("/health", headers={"X-Request-ID": "req-test"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["requestId"] == "req-test"
    assert response.headers["X-Request-ID"] == "req-test"


def test_validate_state_and_analysis_routes_use_domain_services():
    client = TestClient(create_app())
    payload = scenario_payload()

    validation = client.post("/v1/scenarios/validate", json=payload)
    assert validation.status_code == 200
    assert validation.json()["valid"]
    assert validation.json()["finalState"]["pot"] == 200
    assert validation.json()["finalState"]["legalActions"]["actorSeat"] == 1

    state = client.post("/v1/scenarios/state", json=payload)
    assert state.status_code == 200
    assert len(state.json()["snapshots"]) >= 2

    analysis = client.post("/v1/analysis", json=payload)
    assert analysis.status_code == 200
    assert analysis.json()["analysis"]["evidence"]["items"]
    assert analysis.json()["analysis"]["equity"]["sourceLevel"] == "enumerated"

    teaching = client.post("/v1/teaching", json={"scenario": payload, "question": "为什么？"})
    assert teaching.status_code == 200
    assert teaching.json()["teacherVersion"] == "teaching-core-0.1"
    assert teaching.json()["response"]["summary"]["evidenceReferences"]


def test_api_returns_stable_validation_and_replay_errors():
    client = TestClient(create_app())
    invalid_model = scenario_payload()
    invalid_model["heroHoleCards"] = ["As", "As"]
    response = client.post("/v1/scenarios/validate", json=invalid_model)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_scenario"
    assert response.json()["requestId"]

    illegal = scenario_payload()
    illegal["actionHistory"][0] = {
        "actionId": "bad-check",
        "sequence": 1,
        "street": "preflop",
        "actorSeat": 0,
        "actionType": "check",
    }
    response = client.post("/v1/scenarios/validate", json=illegal)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "check_not_legal"
    assert response.json()["error"]["details"]["legalActions"]


def test_range_parse_route_returns_normalized_range():
    client = TestClient(create_app())
    response = client.post("/v1/ranges/parse", json={"notation": "22+, A5s+"})

    assert response.status_code == 200
    matrix = response.json()["range"]["matrix169"]
    assert matrix["22"] == "1"
    assert matrix["AA"] == "1"
    assert matrix["A5s"] == "1"


def test_saved_scenario_crud_and_analysis_history():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = {"scenario": scenario_payload(), "title": "Review spot", "tags": ["flop"]}

    created = client.post("/v1/scenarios", json=payload)
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["scenarioId"]
    assert created.json()["scenario"]["revisionNo"] == 1

    listed = client.get("/v1/scenarios", params={"q": "Review"})
    assert listed.status_code == 200
    assert listed.json()["scenarios"][0]["scenarioId"] == scenario_id

    updated_payload = {**payload, "title": "Updated spot", "tags": ["saved"]}
    updated = client.put(f"/v1/scenarios/{scenario_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["scenario"]["revisionNo"] == 2

    copied = client.post(f"/v1/scenarios/{scenario_id}/copy", json={})
    assert copied.status_code == 200
    assert copied.json()["scenario"]["scenarioId"] != scenario_id

    favorite = client.post(f"/v1/scenarios/{scenario_id}/favorite", json={"favorite": True})
    assert favorite.json()["scenario"]["favorite"] is True

    analyzed = client.post(f"/v1/scenarios/{scenario_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["analysisRun"]["status"] == "completed"

    history = client.get(f"/v1/scenarios/{scenario_id}/analyses")
    assert len(history.json()["analyses"]) == 1

    deleted = client.delete(f"/v1/scenarios/{scenario_id}")
    assert deleted.status_code == 200
    assert client.get(f"/v1/scenarios/{scenario_id}").status_code == 404
