from fastapi.testclient import TestClient
import pytest
import time

from poker_coach.api import AppConfig, create_app
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


def test_api_enforces_configured_rate_limit_and_analysis_timeout_cap():
    rate_limited = TestClient(
        create_app(
            AppConfig(rate_limit_per_minute=2),
            store=SQLiteStore(":memory:"),
        )
    )
    assert rate_limited.get("/health").status_code == 200
    assert rate_limited.get("/health").status_code == 200
    limited = rate_limited.get("/health")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert limited.headers["Retry-After"] == "60"

    capped = TestClient(
        create_app(
            AppConfig(max_timeout_seconds=1, rate_limit_per_minute=0),
            store=SQLiteStore(":memory:"),
        )
    )
    timeout = capped.post(
        "/v1/analysis?timeoutSeconds=2",
        json=scenario_payload(),
    )
    assert timeout.status_code == 422
    assert timeout.json()["error"]["code"] == "timeout_too_large"


def test_request_audit_log_contains_safe_observability_fields(caplog):
    caplog.set_level("INFO", logger="poker_coach.api")
    client = TestClient(create_app(store=SQLiteStore(":memory:")))

    response = client.post(
        "/v1/scenarios/validate",
        json=scenario_payload(),
        headers={"X-Anonymous-Session": "anon-test"},
    )

    assert response.status_code == 200
    records = [record for record in caplog.records if record.name == "poker_coach.api"]
    assert records
    record = records[-1]
    assert record.method == "POST"
    assert record.path == "/v1/scenarios/validate"
    assert record.status_code == 200
    assert record.scenario_hash
    assert record.anonymous_session == "anon-test"
    assert record.cache_hit is False


def test_local_web_origin_is_allowed_by_cors():
    client = TestClient(create_app())
    response = client.options(
        "/v1/scenarios/state",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


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


def test_state_route_replays_only_through_decision_point():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()
    payload["actionHistory"].append(
        {
            "actionId": "future-check",
            "sequence": 4,
            "street": "flop",
            "actorSeat": 1,
            "actionType": "check",
        }
    )
    response = client.post("/v1/scenarios/state", json=payload)

    assert response.status_code == 200
    assert response.json()["finalState"]["actorSeat"] == 1
    assert response.json()["finalState"]["legalActions"]["actions"]


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


def test_api_rejects_a_decision_point_that_does_not_match_replayed_state():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()
    payload["decisionPoint"]["actorSeat"] = 0
    response = client.post("/v1/scenarios/validate", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "decision_point_actor_mismatch"
    assert response.json()["error"]["details"]["state"]["actorSeat"] == 1


def test_range_parse_route_returns_normalized_range():
    client = TestClient(create_app())
    response = client.post("/v1/ranges/parse", json={"notation": "22+, A5s+"})

    assert response.status_code == 200
    matrix = response.json()["range"]["matrix169"]
    assert matrix["22"] == "1"
    assert matrix["AA"] == "1"
    assert matrix["A5s"] == "1"
    assert response.json()["summary"]["totalCombos"] > 0
    assert response.json()["combos"]


def test_equity_route_returns_equity_and_evidence():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    response = client.post("/v1/analysis/equity", json=scenario_payload())

    assert response.status_code == 200
    assert response.json()["equity"]["sourceLevel"] == "enumerated"
    assert "equity.hero" in {item["evidenceId"] for item in response.json()["evidence"]["items"]}


def test_equity_route_rejects_missing_villain_assumption():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = {**scenario_payload(), "villainHoleCards": None}
    response = client.post("/v1/analysis/equity", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "equity_unavailable"


def test_teaching_free_text_is_not_persisted_by_default():
    store = SQLiteStore(":memory:")
    client = TestClient(create_app(store=store))
    response = client.post(
        "/v1/teaching",
        json={
            "scenario": scenario_payload(),
            "profileId": "privacy-profile",
            "question": "sensitive user note",
        },
    )

    assert response.status_code == 200
    assert store._connection.execute(
        "SELECT user_question FROM teaching_sessions"
    ).fetchone()[0] is None
    store.close()


def test_teaching_free_text_can_be_explicitly_enabled():
    store = SQLiteStore(":memory:")
    client = TestClient(create_app(store=store, config=AppConfig(store_user_text=True)))
    response = client.post(
        "/v1/teaching",
        json={
            "scenario": scenario_payload(),
            "profileId": "privacy-profile",
            "question": "keep this question",
        },
    )

    assert response.status_code == 200
    assert store._connection.execute(
        "SELECT user_question FROM teaching_sessions"
    ).fetchone()[0] == "keep this question"
    store.close()


def test_saved_scenario_crud_and_analysis_history():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    raw_payload_scenario = {**scenario_payload(), "heroHoleCards": ["kd", "as"]}
    payload = {"scenario": raw_payload_scenario, "title": "Review spot", "tags": ["flop"]}

    created = client.post("/v1/scenarios", json=payload)
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["scenarioId"]
    assert created.json()["scenario"]["revisionNo"] == 1
    assert created.json()["scenario"]["rawScenario"]["heroHoleCards"] == ["kd", "as"]
    assert created.json()["scenario"]["scenario"]["heroHoleCards"] == ["Kd", "As"]

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
    assert analyzed.json()["analysisRun"]["rawScenario"]["heroHoleCards"] == ["kd", "as"]
    assert analyzed.json()["analysisRun"]["normalizedScenario"]["heroHoleCards"] == ["Kd", "As"]

    changed = {**scenario_payload(), "board": ["2c", "7d", "Qs"]}
    changed_update = {"scenario": changed, "title": "Updated board", "tags": ["saved"]}
    assert client.put(f"/v1/scenarios/{scenario_id}", json=changed_update).status_code == 200
    second_analyzed = client.post(f"/v1/scenarios/{scenario_id}/analyze")
    assert second_analyzed.status_code == 200

    history = client.get(f"/v1/scenarios/{scenario_id}/analyses")
    assert len(history.json()["analyses"]) == 2
    left_id, right_id = [item["analysisId"] for item in history.json()["analyses"]]
    compared = client.get(
        f"/v1/scenarios/{scenario_id}/analyses/compare",
        params={"leftAnalysisId": left_id, "rightAnalysisId": right_id},
    )
    assert compared.status_code == 200
    assert any(item["field"] == "board" for item in compared.json()["differences"])

    deleted = client.delete(f"/v1/scenarios/{scenario_id}")
    assert deleted.status_code == 200
    assert client.get(f"/v1/scenarios/{scenario_id}").status_code == 404


def test_saved_scenario_rejects_duplicate_tags():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    response = client.post(
        "/v1/scenarios",
        json={"scenario": scenario_payload(), "title": "Duplicate tags", "tags": ["flop", "flop"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_tags"


def test_saved_scenario_rejects_illegal_action_history_on_the_server():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()
    payload["actionHistory"][1]["actorSeat"] = 0
    response = client.post(
        "/v1/scenarios",
        json={"scenario": payload, "title": "Illegal saved scene", "tags": []},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"wrong_actor", "illegal_action"}


def test_historical_revision_can_be_loaded_and_reanalyzed():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    first = {"scenario": scenario_payload(), "title": "Revision source", "tags": ["first"]}
    created = client.post("/v1/scenarios", json=first)
    scenario_id = created.json()["scenario"]["scenarioId"]
    second = {**first, "scenario": {**scenario_payload(), "board": ["2c", "7d", "Qs"]}, "tags": ["second"]}
    assert client.put(f"/v1/scenarios/{scenario_id}", json=second).status_code == 200

    revisions = client.get(f"/v1/scenarios/{scenario_id}/revisions")
    assert revisions.status_code == 200
    assert [item["revisionNo"] for item in revisions.json()["revisions"]] == [2, 1]

    analyzed = client.post(f"/v1/scenarios/{scenario_id}/revisions/1/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["revisionNo"] == 1
    assert analyzed.json()["analysisRun"]["revisionNo"] == 1
    assert analyzed.json()["analysisRun"]["normalizedScenario"]["board"] == ["2c", "7d", "Jh"]


def test_strategy_defaults_and_learning_practice_routes():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()

    matched = client.post("/v1/strategies/match", json=payload)
    assert matched.status_code == 200
    assert matched.json()["strategyMatch"]["level"] in {"exact", "compatible", "approximate", "no_match"}

    defaults = client.get("/v1/ranges/defaults")
    assert defaults.status_code == 200
    assert set(defaults.json()["ranges"]) == {
        "btn_open",
        "bb_defend",
        "bb_3bet",
        "btn_vs_3bet",
        "btn_4bet",
        "bb_vs_4bet",
    }

    profile = client.post("/v1/learning/profiles", json={"profileId": "api-profile"})
    assert profile.status_code == 200
    assert profile.json()["profile"]["profileId"] == "api-profile"

    question = client.post(
        "/v1/practice/generate",
        json={"scenario": payload, "profileId": "api-profile", "mistakeTag": "pot_odds"},
    )
    assert question.status_code == 200
    question_id = question.json()["question"]["questionId"]
    assert "expectedAction" not in question.json()["question"]

    attempt = client.post(
        f"/v1/practice/{question_id}/attempt",
        json={"selectedAction": "check", "rationale": "free check at this node"},
    )
    assert attempt.status_code == 200
    assert attempt.json()["outcome"]["profile"]["textureAttempts"]
    assert attempt.json()["outcome"]["attempt"]["questionId"] == question_id
    assert attempt.json()["outcome"]["evidenceReferences"]

    teaching = client.post(
        "/v1/teaching",
        json={"scenario": payload, "profileId": "api-profile", "depth": "beginner"},
    )
    assert teaching.status_code == 200
    assert teaching.json()["session"]["sessionId"]
    assert teaching.json()["teacherVersion"] == "teaching-core-0.1"
    assert teaching.json()["promptVersion"] == "teaching-prompt-0.1"
    assert teaching.json()["response"]["explanationDepth"] == "beginner"

    invalid_depth = client.post(
        "/v1/teaching",
        json={"scenario": payload, "depth": "expert"},
    )
    assert invalid_depth.status_code == 422
    assert invalid_depth.json()["error"]["code"] == "invalid_teaching_depth"

    deleted_profile = client.delete("/v1/learning/profiles/api-profile")
    assert deleted_profile.status_code == 200
    assert client.get("/v1/learning/profiles/api-profile").status_code == 404


def test_analysis_idempotency_replays_same_result_and_rejects_conflict():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()
    first = client.post("/v1/analysis", json=payload, headers={"Idempotency-Key": "analysis-1"})
    second = client.post("/v1/analysis", json=payload, headers={"Idempotency-Key": "analysis-1"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotentReplay"] is True
    assert second.json()["analysis"] == first.json()["analysis"]

    conflict = {**payload, "heroHoleCards": ["As", "Qd"]}
    response = client.post("/v1/analysis", json=conflict, headers={"Idempotency-Key": "analysis-1"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


def test_analysis_job_can_be_submitted_and_polled():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    response = client.post("/v1/analysis/jobs", json=scenario_payload())

    assert response.status_code == 202
    job_id = response.json()["jobId"]
    final = None
    for _ in range(30):
        final = client.get(f"/v1/analysis/jobs/{job_id}")
        if final.json()["status"] in {"completed", "failed", "cancelled", "timeout"}:
            break
        time.sleep(0.02)
    assert final is not None
    assert final.status_code == 200
    assert final.json()["status"] == "completed"
    assert final.json()["analysis"]["evidence"]["items"]


def test_analysis_job_cancellation_is_forwarded_to_equity_engine():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    payload = scenario_payload()
    payload["board"] = []
    payload["actionHistory"] = []
    payload["decisionPoint"] = {"street": "preflop", "actorSeat": 0, "afterSequence": 0}
    payload["assumptions"] = {
        "equityAlgorithm": "monte_carlo",
        "simulationTrials": 1_000_000,
        "randomSeed": 42,
    }
    submitted = client.post("/v1/analysis/jobs", json=payload)
    job_id = submitted.json()["jobId"]
    cancelled = client.delete(f"/v1/analysis/jobs/{job_id}")

    assert cancelled.status_code == 202
    final = None
    for _ in range(50):
        final = client.get(f"/v1/analysis/jobs/{job_id}")
        if final.json()["status"] in {"completed", "failed", "cancelled", "timeout"}:
            break
        time.sleep(0.02)
    assert final is not None
    assert final.json()["status"] in {"cancelled", "completed"}
