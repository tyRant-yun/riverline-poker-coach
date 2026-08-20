"""Focused contract tests for the R8 Advisor/Solver reconciliation seam."""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.domain.models import Street
from poker_coach.persistence import SQLiteHandEventStore, SQLiteGameSessionStore
from poker_coach.simulator.contracts import AmountSemanticsV1, LegalActionV1, SimulatorActionV1
from poker_coach.simulator.continuous_table import ContinuousTableService
from poker_coach.simulator.decision_reconciliation import (
    ReconciliationIdentityV1,
    reconcile_decision,
    unavailable_simulation,
)


IDENTITY = ReconciliationIdentityV1(
    fingerprint="f" * 64, hand_id="hand-1", sequence=9, street=Street.FLOP
)
LEGAL = (
    LegalActionV1(action=SimulatorActionV1.FOLD, amount_semantics=AmountSemanticsV1.NONE),
    LegalActionV1(action=SimulatorActionV1.CALL, amount_semantics=AmountSemanticsV1.COST, min_amount=100, max_amount=100),
    LegalActionV1(action=SimulatorActionV1.RAISE, amount_semantics=AmountSemanticsV1.TO, min_amount=300, max_amount=1_100),
)


def _result(*, status="ready", action="call", semantics="cost", amount=100, **extra):
    return {
        "status": status,
        "recommendedAction": None if action is None else {
            "action": action, "amountSemantics": semantics, "amount": amount,
        },
        "source": extra.pop("source", "test"), "version": "v1",
        "decision": extra.pop("decision", IDENTITY.to_dict()),
        "limitations": extra.pop("limitations", []), **extra,
    }


def _reconcile(advisor, solver):
    return reconcile_decision(
        identity=IDENTITY, legal_actions=LEGAL, pot=500, hero_stack=1_000,
        hero_commitment=100, advisor=advisor, solver=solver,
    ).to_dict()


def test_exact_legal_actions_are_compared_without_a_final_recommendation():
    result = _reconcile(_result(), _result())
    assert result["agreement"]["kind"] == "exact_action"
    assert "finalRecommendation" not in result
    assert result["ruleBaseline"]["role"] == "rule_baseline"
    assert result["simulationEstimate"]["role"] == "simulation_estimate"


def test_action_and_sizing_disagreements_are_structured_and_raise_to_is_preserved():
    action_difference = _reconcile(_result(action="fold", semantics="none", amount=None), _result())
    assert action_difference["agreement"]["kind"] == "different_action"
    assert action_difference["agreement"]["reasonCodes"] == ["unexplained"]

    sizing_difference = _reconcile(
        _result(action="raise", semantics="to", amount=300),
        _result(action="raise", semantics="to", amount=1_100),
    )
    action = sizing_difference["simulationEstimate"]["action"]
    assert sizing_difference["agreement"]["kind"] == "same_action_different_sizing"
    assert "sizing_set_mismatch" in sizing_difference["agreement"]["reasonCodes"]
    assert action == {"schemaVersion": 1, "action": "raise", "amountSemantics": "to", "amountChips": 1100, "potPct": "200", "isJam": True}


def test_degraded_and_unavailable_solver_leave_the_rule_baseline_usable():
    degraded = _reconcile(_result(), _result(status="degraded", limitations=["bounded model"]))
    assert degraded["status"] == "degraded"
    assert "solver_degraded" in degraded["agreement"]["reasonCodes"]

    unavailable = _reconcile(_result(), unavailable_simulation(IDENTITY))
    assert unavailable["ruleBaseline"]["status"] == "ready"
    assert unavailable["simulationEstimate"]["status"] == "unavailable"
    assert unavailable["agreement"]["kind"] == "insufficient_evidence"
    assert "solver_unavailable" in unavailable["agreement"]["reasonCodes"]


def test_stale_terminal_or_non_hero_identity_cannot_be_combined():
    stale = _result(decision={**IDENTITY.to_dict(), "fingerprint": "old"})
    result = _reconcile(_result(), stale)
    assert result["simulationEstimate"]["status"] == "not_ready"
    assert result["agreement"]["kind"] == "insufficient_evidence"


def test_invalid_amount_and_private_poison_are_never_exposed_or_accepted():
    private_poison = _result(action="raise", semantics="to", amount=9_999, opponentHoleCards=["As", "Ah"])
    result = _reconcile(_result(), private_poison)
    assert result["simulationEstimate"]["status"] == "not_ready"
    assert "opponentHoleCards" not in str(result)
    assert "As" not in str(result)


def test_contract_is_deterministic_and_does_not_claim_ci_overlap_without_two_ev_intervals():
    advisor = _result()
    solver = _result()
    solver["recommendedAction"]["confidenceInterval95"] = {"lower": "1", "upper": "2"}
    first = _reconcile(advisor, solver)
    second = _reconcile(advisor, solver)
    assert first == second
    assert first["agreement"]["confidenceInterval"] == {
        "schemaVersion": 1, "status": "available", "overlap": None,
    }


def _table_client(tmp_path):
    path = tmp_path / "reconciliation.sqlite3"
    service = ContinuousTableService(
        session_store=SQLiteGameSessionStore(path), event_store=SQLiteHandEventStore(path),
        metadata_path=path,
    )
    return TestClient(create_app(config=AppConfig(rate_limit_per_minute=0), table_service=service)), service


def _create_table(client):
    response = client.post("/v1/tables", json={"schemaVersion": 1, "commandId": "r8-create", "seed": 24680})
    assert response.status_code == 200, response.text
    return response.json()["table"]


def _reconcile_api(client, table, *, fingerprint=None):
    return client.post(
        f"/v1/tables/{table['sessionId']}/reconciliation",
        json={"handId": table["handId"], "decisionFingerprint": fingerprint or table["fingerprint"], "budgetTier": "quick"},
    )


def _hero_action(client, table, command_id):
    legal = table["heroLegalActions"][0]
    payload = {
        "schemaVersion": 1, "commandId": command_id, "handId": table["handId"],
        "expectedRevision": table["revision"], "action": legal["action"],
        "amountSemantics": legal["amountSemantics"],
    }
    if legal.get("minAmount") is not None:
        payload["amount"] = legal["minAmount"]
    response = client.post(f"/v1/tables/{table['sessionId']}/actions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["table"]


def test_endpoint_uses_one_current_hero_identity_and_solver_failure_is_nonblocking(tmp_path, monkeypatch):
    client, service = _table_client(tmp_path)
    table = _create_table(client)
    baseline = _reconcile_api(client, table)
    assert baseline.status_code == 200, baseline.text
    payload = baseline.json()["reconciliation"]
    assert payload["decision"]["fingerprint"] == table["fingerprint"]
    assert "holeCards" not in str(payload)

    monkeypatch.setattr(service._fast_solver, "solve", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("solver poison")))
    fallback = _reconcile_api(client, table)
    assert fallback.status_code == 200, fallback.text
    result = fallback.json()["reconciliation"]
    assert result["ruleBaseline"]["status"] in {"ready", "degraded"}
    assert result["simulationEstimate"]["status"] == "unavailable"
    assert "solver poison" not in str(result)

    monkeypatch.setattr(service, "_actor", lambda _events: 1)
    table = client.get(f"/v1/tables/{table['sessionId']}").json()["table"]
    non_hero = _reconcile_api(client, table)
    assert non_hero.status_code == 200, non_hero.text
    assert non_hero.json()["reconciliation"]["status"] == "not_ready"
    monkeypatch.undo()
    table = client.get(f"/v1/tables/{table['sessionId']}").json()["table"]

    table = _hero_action(client, table, "advance")
    stale = _reconcile_api(client, table, fingerprint="old")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_decision"
    service.close()


def test_terminal_endpoint_is_not_ready_and_never_splices_old_advice(tmp_path):
    client, service = _table_client(tmp_path)
    table = _create_table(client)
    for turn in range(30):
        if table["handComplete"]:
            break
        table = _hero_action(client, table, f"finish-{turn}")
    assert table["handComplete"]
    response = _reconcile_api(client, table)
    assert response.status_code == 200, response.text
    result = response.json()["reconciliation"]
    assert result["status"] == "not_ready"
    assert result["agreement"]["kind"] == "insufficient_evidence"
    assert result["ruleBaseline"]["action"] is None
    service.close()
