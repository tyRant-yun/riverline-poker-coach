"""J10/J11 agent-wiring audit; intentionally outside ``backend/tests``.

Run explicitly with Python 3.13:
``py -3.13 -m pytest audits/agent_teaching -q``.

The final test is intentionally red on the current implementation.  It is a
release-audit signal, not a regression test admitted to the normal green gate:
the whole-hand endpoint currently does not invoke the supported Teacher seam.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from poker_coach.api import create_app
from poker_coach.coach import ExternalModelTeacher
from poker_coach.persistence import SQLiteStore


def _action(
    sequence: int,
    actor_seat: int,
    action_type: str,
    *,
    street: str = "preflop",
    amount: int | None = None,
    amount_type: str = "none",
) -> dict[str, object]:
    event: dict[str, object] = {
        "actionId": f"a{sequence}",
        "sequence": sequence,
        "street": street,
        "actorSeat": actor_seat,
        "actionType": action_type,
    }
    if amount is not None:
        event.update(amount=amount, amountType=amount_type)
    return event


def _flop_node_payload() -> dict[str, object]:
    """One valid current node; no future cards are supplied to this request."""

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
            _action(1, 0, "call", amount=50, amount_type="cost"),
            _action(2, 1, "check"),
            _action(3, 0, "deal_flop", street="flop"),
        ],
        "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
        "assumptions": {"equityAlgorithm": "monte_carlo", "simulationTrials": 20, "randomSeed": 7},
    }


def _completed_hand_payload() -> dict[str, object]:
    """Eight real decisions plus a future turn/river for isolation auditing."""

    payload = _flop_node_payload()
    payload.update(
        board=["2c", "7d", "Jh", "9s", "3h"],
        actionHistory=[
            _action(1, 0, "call", amount=50, amount_type="cost"),
            _action(2, 1, "check"),
            _action(3, 0, "deal_flop", street="flop"),
            _action(4, 1, "check", street="flop"),
            _action(5, 0, "check", street="flop"),
            _action(6, 0, "deal_turn", street="turn"),
            _action(7, 1, "check", street="turn"),
            _action(8, 0, "check", street="turn"),
            _action(9, 0, "deal_river", street="river"),
            _action(10, 1, "check", street="river"),
            _action(11, 0, "check", street="river"),
        ],
        decisionPoint={"street": "river", "actorSeat": 0, "afterSequence": 11},
    )
    return payload


Mode = Literal["success", "timeout", "schema_drift", "invalid_evidence"]


@dataclass
class RecordingTransport:
    """Deterministic OpenAI-compatible fake at ExternalModelTeacher's public seam."""

    mode: Mode = "success"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, system: str, user: str, model: str, timeout: float) -> dict[str, Any]:
        facts = json.loads(user.split("## 牌局事实与证据\n", 1)[1].split("\n\n## 教学深度", 1)[0])
        self.calls.append({"system": system, "facts": facts, "model": model, "timeout": timeout})
        if self.mode == "timeout":
            raise TimeoutError("audit transport timeout")
        if self.mode == "schema_drift":
            return {"summary": "not a TeachingResponse"}
        evidence_id = facts["evidence"][0]["evidenceId"]
        if self.mode == "invalid_evidence":
            return {
                "explanationDepth": "intermediate",
                "summary": {
                    "text": "未经证实的数字 99。",
                    "evidenceReferences": [{"evidenceId": "invented.evidence"}],
                    "containsNumbers": True,
                },
                "uncertainty": {
                    "text": "外部输出已经过当前节点证据校验。",
                    "evidenceReferences": [{"evidenceId": evidence_id}],
                    "containsNumbers": False,
                },
            }
        legal_actions = facts["legalActions"]["actions"]
        return {
            "explanationDepth": "intermediate",
            "summary": {
                "text": "外部 fake 只根据当前节点事实生成教学。",
                "evidenceReferences": [{"evidenceId": evidence_id}],
                "containsNumbers": False,
            },
            "recommendedActions": (
                [{"action": legal_actions[0], "evidenceReferences": [{"evidenceId": evidence_id}]}]
                if legal_actions
                else []
            ),
            "uncertainty": {
                "text": "证据边界限制了这份外部说明。",
                "evidenceReferences": [{"evidenceId": evidence_id}],
                "containsNumbers": False,
            },
        }


def _client(transport: RecordingTransport) -> TestClient:
    teacher = ExternalModelTeacher(
        base_url="http://audit.invalid",
        api_key="audit-key",
        model="audit-model",
        timeout_seconds=0.01,
        transport=transport,
    )
    return TestClient(create_app(store=SQLiteStore(":memory:"), teacher=teacher))


def _assert_external_envelope(body: dict[str, Any], *, degraded: bool) -> None:
    assert body["provider"] == "external_llm"
    assert body["teacherVersion"] == "teaching-external-0.1"
    assert body["promptVersion"] == "teaching-external-prompt-0.1"
    assert body["degraded"] is degraded


def test_single_node_teaching_calls_external_transport_once_with_node_facts() -> None:
    transport = RecordingTransport()
    response = _client(transport).post("/v1/teaching", json={"scenario": _flop_node_payload(), "depth": "intermediate"})

    assert response.status_code == 200, response.text
    _assert_external_envelope(response.json(), degraded=False)
    assert len(transport.calls) == 1
    facts = transport.calls[0]["facts"]
    assert facts["scenario"]["board"] == ["2c", "7d", "Jh"]
    assert facts["scenario"]["actorSeat"] == 1
    assert set(facts["scenario"]["heroHoleCards"]) == {"As", "Kd"}
    assert "9s" not in json.dumps(facts, ensure_ascii=False)


def test_saved_scenario_teaching_calls_same_external_transport_once() -> None:
    transport = RecordingTransport()
    client = _client(transport)
    created = client.post("/v1/scenarios", json={"scenario": _flop_node_payload(), "title": "audit", "tags": []})
    assert created.status_code == 200, created.text

    response = client.post(f"/v1/scenarios/{created.json()['scenario']['scenarioId']}/teach", json={"depth": "beginner"})

    assert response.status_code == 200, response.text
    _assert_external_envelope(response.json(), degraded=False)
    assert len(transport.calls) == 1
    assert transport.calls[0]["facts"]["scenario"]["board"] == ["2c", "7d", "Jh"]


@pytest.mark.parametrize("mode", ["timeout", "schema_drift"])
def test_single_node_external_failure_modes_degrade_to_local_template(mode: Mode) -> None:
    transport = RecordingTransport(mode=mode)
    response = _client(transport).post("/v1/teaching", json={"scenario": _flop_node_payload()})

    assert response.status_code == 200, response.text
    _assert_external_envelope(response.json(), degraded=True)
    assert len(transport.calls) == 1
    assert response.json()["response"]["summary"]["text"] != "外部 fake 只根据当前节点事实生成教学。"


def test_single_node_invalid_evidence_is_sanitized_without_claiming_a_local_agent() -> None:
    transport = RecordingTransport(mode="invalid_evidence")
    response = _client(transport).post("/v1/teaching", json={"scenario": _flop_node_payload()})

    assert response.status_code == 200, response.text
    body = response.json()
    _assert_external_envelope(body, degraded=False)
    assert len(transport.calls) == 1
    assert "99" not in body["response"]["summary"]["text"]
    assert body["response"]["summary"]["evidenceReferences"] == []


def test_hand_review_must_call_external_teacher_once_per_real_decision_and_expose_provenance() -> None:
    """J11 release gate: expected to fail until hand-review Teacher wiring exists.

    The completed fixture has eight player decisions.  A future implementation
    must call the injected Teacher once per node with that node's visible facts,
    then return provider/version/degraded provenance for decisions and summary.
    """

    transport = RecordingTransport()
    response = _client(transport).post("/v1/hand-reviews", json={"scenario": _completed_hand_payload()})

    assert response.status_code == 200, response.text
    body = response.json()
    expected_calls = len(body["review"]["decisionReviews"])
    assert len(transport.calls) == expected_calls, (
        "J11 external-agent wiring missing: expected one bounded Teacher call per "
        f"decision ({expected_calls}), got {len(transport.calls)}"
    )
    assert all("9s" not in json.dumps(call["facts"], ensure_ascii=False) for call in transport.calls[:2])
    assert {"provider", "teacherVersion", "promptVersion", "degraded"} <= set(body["review"])
