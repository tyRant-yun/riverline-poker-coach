"""Black-box contract tests for the deterministic hand-review endpoint."""

from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence import SQLiteStore
from poker_coach.solver import SolveMetadata, SolveResult, SolverHand, SolverJobQueue, SolverNode


def _completed_checkdown_payload(*, include_hole_cards: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
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
        "board": ["2c", "7d", "Jh", "9s", "3h"],
        "actionHistory": [
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
        "decisionPoint": {"street": "river", "actorSeat": 0, "afterSequence": 11},
        "assumptions": {
            "equityAlgorithm": "monte_carlo",
            "simulationTrials": 50,
            "randomSeed": 17,
        },
    }
    if include_hole_cards:
        payload["heroHoleCards"] = ["As", "Kd"]
        payload["villainHoleCards"] = ["Qh", "Jc"]
    return payload


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


def test_hand_review_returns_ordered_node_scoped_analysis_and_evidence():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))

    response = client.post("/v1/hand-reviews", json=_completed_checkdown_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["handReviewVersion"] == "hand-review-1"
    assert body["review"]["sourceKind"] == "aggregated_local"
    assert body["review"]["provider"] == "local"
    assert body["review"]["teacherVersion"] == "hand-review-aggregate-0.1"
    assert body["review"]["promptVersion"] == "hand-review-aggregate-prompt-0.1"
    assert body["review"]["degraded"] is False
    reviews = body["review"]["decisionReviews"]
    assert [review["actionId"] for review in reviews] == [
        "a1",
        "a2",
        "a4",
        "a5",
        "a7",
        "a8",
        "a10",
        "a11",
    ]
    assert [review["eventSequence"] for review in reviews] == [1, 2, 4, 5, 7, 8, 10, 11]
    assert [review["decisionSequence"] for review in reviews] == [0, 1, 3, 4, 6, 7, 9, 10]
    assert [review["actualAction"]["actionId"] for review in reviews] == [
        review["actionId"] for review in reviews
    ]
    assert [len(review["analysisSummary"]["board"]["board"]) for review in reviews] == [
        0,
        0,
        3,
        3,
        4,
        4,
        5,
        5,
    ]
    assert set(reviews[2]["analysisSummary"]["board"]["board"]) == {"2c", "7d", "Jh"}
    assert "9s" not in reviews[2]["stateBeforeAction"]["board"]
    assert reviews[2]["evidenceBundleId"] != reviews[3]["evidenceBundleId"]
    for review in reviews:
        assert review["evidenceBundle"]["items"]
        assert review["solverAssessment"] == {
            "status": "unscored",
            "reason": "solver assessment is not available in deterministic hand-review v1",
            "source": None,
        }
        assert review["rangeUpdate"]["status"] == "unavailable"
        assert review["rangeUpdate"]["actionId"] == review["actionId"]
        assert review["rangeUpdate"]["seatId"] == review["actorSeat"]
        assert review["rangeUpdate"]["afterSequence"] == review["eventSequence"]
        teaching = review["teaching"]
        assert teaching["sourceKind"] == "local_deterministic_template"
        assert teaching["provider"] == "local"
        assert teaching["teacherVersion"] == "teaching-core-0.1"
        assert teaching["promptVersion"] == "teaching-prompt-0.1"
        assert teaching["degraded"] is False


def test_hand_review_returns_curated_combo_range_update_for_default_hu_open():
    """Each real action exposes its post-action actor belief, not a placeholder."""

    payload = _completed_checkdown_payload()
    payload["board"] = []
    payload["actionHistory"] = [
        _action(1, 0, "raise_to", amount=200, amount_type="to"),
    ]
    payload["decisionPoint"] = {"street": "preflop", "actorSeat": 1, "afterSequence": 1}
    payload["rangesBySeat"] = {
        "0": {
            "rangeId": "button-prior",
            "name": "Button prior",
            "version": "1",
            "source": "user_defined",
            "matrix169": {"AA": "1", "J4o": "1"},
        }
    }
    client = TestClient(create_app(store=SQLiteStore(":memory:")))

    response = client.post("/v1/hand-reviews", json=payload)

    assert response.status_code == 200, response.text
    update = response.json()["review"]["decisionReviews"][0]["rangeUpdate"]
    assert update["status"] == "available"
    assert update["actionId"] == "a1"
    assert update["seatId"] == 0
    assert update["afterSequence"] == 1
    assert update["source"] == "preflop_policy"
    assert update["confidence"] == "curated"
    assert update["policy"]["version"] == "hu-100bb-0.1"
    assert update["combos"]["AsAh"]["probability"] != update["combos"]["AsAh"]["priorProbability"]


def test_hand_review_uses_curated_policy_for_each_supported_hu_branch_action():
    payload = _completed_checkdown_payload()
    payload["board"] = []
    payload["actionHistory"] = [
        _action(1, 0, "raise_to", amount=200, amount_type="to"),
        _action(2, 1, "call", amount=100, amount_type="cost"),
    ]
    payload["decisionPoint"] = {"street": "preflop", "actorSeat": 0, "afterSequence": 2}
    payload["rangesBySeat"] = {
        "0": {"rangeId": "btn", "name": "BTN", "version": "1", "source": "user_defined", "matrix169": {"AA": "1", "J4o": "1"}},
        "1": {"rangeId": "bb", "name": "BB", "version": "1", "source": "user_defined", "matrix169": {"76s": "1", "72o": "1"}},
    }

    response = TestClient(create_app(store=SQLiteStore(":memory:"))).post("/v1/hand-reviews", json=payload)

    assert response.status_code == 200, response.text
    updates = [item["rangeUpdate"] for item in response.json()["review"]["decisionReviews"]]
    assert [(item["actionId"], item["afterSequence"], item["status"]) for item in updates] == [
        ("a1", 1, "available"),
        ("a2", 2, "available"),
    ]
    assert all(item["source"] == "preflop_policy" for item in updates)


def test_hand_review_uses_curated_policy_for_8max_rfi():
    positions = ("button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co")
    payload = {
        "schemaVersion": 2, "gameVariant": "nlhe", "tableSize": 8,
        "smallBlind": 50, "bigBlind": 100, "buttonSeat": 0, "heroSeat": 3,
        "seats": [{"seatId": seat, "startingStack": 10000, "position": position} for seat, position in enumerate(positions)],
        "board": [],
        "actionHistory": [_action(1, 3, "raise_to", amount=250, amount_type="to")],
        "decisionPoint": {"street": "preflop", "actorSeat": 4, "afterSequence": 1},
        "assumptions": {},
        "rangesBySeat": {"3": {"rangeId": "utg", "name": "UTG", "version": "1", "source": "user_defined", "matrix169": {"AA": "1", "A5s": "1"}}},
    }

    response = TestClient(create_app(store=SQLiteStore(":memory:"))).post("/v1/hand-reviews", json=payload)

    assert response.status_code == 200, response.text
    update = response.json()["review"]["decisionReviews"][0]["rangeUpdate"]
    assert update["status"] == "available"
    assert update["source"] == "preflop_policy"
    assert update["policy"]["version"] == "8max-rfi-100bb-0.1"
    assert update["policy"]["node"].endswith("8max-rfi-utg-2.5bb")


def test_hand_review_range_update_is_honest_for_unsupported_hu_limp():
    payload = _completed_checkdown_payload()
    payload["board"] = []
    payload["actionHistory"] = [_action(1, 0, "call", amount=50, amount_type="cost")]
    payload["decisionPoint"] = {"street": "preflop", "actorSeat": 1, "afterSequence": 1}
    payload["rangesBySeat"] = {"0": {"rangeId": "btn", "name": "BTN", "version": "1", "source": "user_defined", "matrix169": {"AA": "1"}}}

    response = TestClient(create_app(store=SQLiteStore(":memory:"))).post("/v1/hand-reviews", json=payload)

    assert response.status_code == 200, response.text
    update = response.json()["review"]["decisionReviews"][0]["rangeUpdate"]
    assert update["status"] == "unavailable"
    assert "limp" in update["reason"]
    assert update["combos"] is None


def test_hand_review_range_update_does_not_see_future_board_cards():
    payload = _completed_checkdown_payload()
    payload["actionHistory"][0] = _action(1, 0, "raise_to", amount=200, amount_type="to")
    payload["actionHistory"][1] = _action(2, 1, "call", amount=100, amount_type="cost")
    payload["rangesBySeat"] = {"0": {"rangeId": "btn", "name": "BTN", "version": "1", "source": "user_defined", "matrix169": {"A2s": "1", "J4o": "1"}}}

    response = TestClient(create_app(store=SQLiteStore(":memory:"))).post("/v1/hand-reviews", json=payload)

    assert response.status_code == 200, response.text
    reviews = response.json()["review"]["decisionReviews"]
    assert {"a3", "a6", "a9"}.isdisjoint(item["actionId"] for item in reviews)
    update = reviews[0]["rangeUpdate"]
    assert update["status"] == "available"
    assert "2c" in payload["board"]
    assert "Ac2c" in update["combos"]  # future board cards did not block the open node


def test_hand_review_attaches_one_ordered_teaching_per_real_action_without_future_facts():
    """Teaching is node-local even when the imported scenario contains a runout."""

    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    response = client.post("/v1/hand-reviews", json=_completed_checkdown_payload())

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    decisions = review["decisionReviews"]
    assert len(decisions) == 8
    assert [item["actionId"] for item in decisions] == review["handSummary"]["reviewedActionIds"]
    assert all(item["teaching"] is not None for item in decisions)
    assert [item["teaching"]["teachingVersion"] for item in decisions] == [
        "hand-review-teaching-1"
    ] * len(decisions)

    earliest = decisions[0]
    teaching_blob = str(earliest["teaching"])
    # The future turn and river cards are not visible before a1 and cannot be
    # present in the local teaching's text or evidence references.
    assert "9s" not in teaching_blob
    assert "3h" not in teaching_blob
    bundle_ids = {item["evidenceId"] for item in earliest["evidenceBundle"]["items"]}
    for text in (
        earliest["teaching"]["summary"],
        earliest["teaching"]["uncertainty"],
        *earliest["teaching"]["keyPoints"],
    ):
        assert {ref["evidenceId"] for ref in text["evidenceReferences"]} <= bundle_ids

    assert review["wholeHandSummary"]["summary"]
    assert review["priorityFindings"] == []


def test_unscored_and_no_policy_teaching_are_honest_principle_only_language():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    response = client.post("/v1/hand-reviews", json=_completed_checkdown_payload())

    assert response.status_code == 200, response.text
    teaching = response.json()["review"]["decisionReviews"][0]["teaching"]
    text = " ".join(
        [teaching["summary"]["text"], teaching["uncertainty"]["text"]]
        + [point["text"] for point in teaching["keyPoints"]]
    )
    assert teaching["mode"] == "principle_only"
    assert "Solver 错误" not in text
    assert "策略失误" not in text
    assert "EV 损失" not in text
    assert "no_policy" in text


def test_hand_review_honestly_degrades_when_hole_cards_and_equity_are_unavailable():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))

    response = client.post(
        "/v1/hand-reviews",
        json=_completed_checkdown_payload(include_hole_cards=False),
    )

    assert response.status_code == 200
    reviews = response.json()["review"]["decisionReviews"]
    assert all(review["analysisSummary"]["equity"] is None for review in reviews)
    assert all(review["analysisSummary"]["hand"] is None for review in reviews)
    assert any("missing" in warning for warning in reviews[0]["warnings"])


def _flop_node_payload() -> dict[str, object]:
    """The exact node before BB's flop check (a4) in the checkdown hand."""

    payload = _completed_checkdown_payload()
    payload["actionHistory"] = payload["actionHistory"][:3]
    payload["decisionPoint"] = {"street": "flop", "actorSeat": 1, "afterSequence": 3}
    payload["rangesBySeat"] = {
        "0": {
            "rangeId": "button-range",
            "name": "Button range",
            "version": "1",
            "source": "user_defined",
            "matrix169": {"76s": "1"},
        },
        "1": {
            "rangeId": "bb-range",
            "name": "BB range",
            "version": "1",
            "source": "user_defined",
            "matrix169": {"T8s": "1"},
        },
    }
    return payload


def _solver_result(*, check_frequency: float, combo: str = "QhJc") -> SolveResult:
    return SolveResult(
        metadata=SolveMetadata(
            solver="test-solver",
            version="1",
            street="flop",
            max_iterations=1,
            exploitability_chips=0,
            target_exploitability_chips=0,
        ),
        root=SolverNode(
            actions=("Check", "Bet(250)"),
            player=0,
            hands=(
                SolverHand(
                    combo=combo,
                    weight=1,
                    equity=0,
                    ev=0,
                    strategy={"Check": check_frequency, "Bet(250)": 1 - check_frequency},
                ),
            ),
        ),
    )


def test_hand_review_solver_assessment_uses_verified_job_and_product_threshold():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    client = TestClient(
        create_app(config=AppConfig(), store=SQLiteStore(":memory:"), solver_queue=queue)
    )
    try:
        submitted = client.post("/v1/solve/jobs", json={"scenario": _flop_node_payload()})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(job_id, status="solved", result=_solver_result(check_frequency=0.05))
        review_scenario = _completed_checkdown_payload()
        review_scenario["rangesBySeat"] = _flop_node_payload()["rangesBySeat"]

        response = client.post(
            "/v1/hand-reviews",
            json={
                "scenario": review_scenario,
                "solverJobs": {"a4": job_id},
            },
        )

        assert response.status_code == 200, response.text
        assessment = response.json()["review"]["decisionReviews"][2]["solverAssessment"]
        assert assessment == {
            "status": "mixed",
            "reason": None,
            "source": "solver",
            "confidence": "grounded",
            "actualFrequency": 0.05,
            "primaryAction": "Bet(250)",
            "thresholdMetadata": {
                "mixedThreshold": 0.05,
                "kind": "product_interpretation",
            },
            "actionMapping": {
                "status": "exact",
                "policyAction": "Check",
                "observedSize": None,
                "mappedSize": None,
                "offTree": False,
            },
        }
        assert all(
            review["solverAssessment"]["status"] == "unscored"
            for review in response.json()["review"]["decisionReviews"][:2]
        )
    finally:
        queue.close()


def test_hand_review_range_update_reuses_only_the_verified_solver_artifact():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    client = TestClient(create_app(config=AppConfig(), store=SQLiteStore(":memory:"), solver_queue=queue))
    try:
        review_scenario = _completed_checkdown_payload()
        review_scenario["actionHistory"][0] = _action(1, 0, "raise_to", amount=200, amount_type="to")
        review_scenario["actionHistory"][1] = _action(2, 1, "call", amount=100, amount_type="cost")
        review_scenario["rangesBySeat"] = {
            "0": {"rangeId": "btn", "name": "BTN", "version": "1", "source": "user_defined", "matrix169": {"AA": "1"}},
            "1": {"rangeId": "bb", "name": "BB", "version": "1", "source": "user_defined", "matrix169": {"76s": "1"}}
        }
        node_scenario = {
            **review_scenario,
            "actionHistory": review_scenario["actionHistory"][:3],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
        }
        submitted = client.post("/v1/solve/jobs", json={"scenario": node_scenario})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(job_id, status="solved", result=_solver_result(check_frequency=0.8, combo="7s6s"))

        response = client.post("/v1/hand-reviews", json={"scenario": review_scenario, "solverJobs": {"a4": job_id}})

        assert response.status_code == 200, response.text
        update = response.json()["review"]["decisionReviews"][2]["rangeUpdate"]
        assert update["status"] == "available"
        assert update["source"] == "solver"
        assert update["confidence"] == "grounded"
        assert update["afterSequence"] == 4
        assert update["policy"]["node"] == "flop"
    finally:
        queue.close()


@pytest.mark.parametrize(
    ("check_frequency", "expected_status"),
    ((0.8, "primary"), (0.05, "mixed"), (0.049, "rare"), (0.0, "absent")),
)
def test_hand_review_solver_assessment_statuses_use_the_product_threshold(
    check_frequency: float, expected_status: str
):
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    client = TestClient(
        create_app(config=AppConfig(), store=SQLiteStore(":memory:"), solver_queue=queue)
    )
    try:
        node_scenario = _flop_node_payload()
        submitted = client.post("/v1/solve/jobs", json={"scenario": node_scenario})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(job_id, status="solved", result=_solver_result(check_frequency=check_frequency))
        review_scenario = _completed_checkdown_payload()
        review_scenario["rangesBySeat"] = node_scenario["rangesBySeat"]

        response = client.post(
            "/v1/hand-reviews",
            json={"scenario": review_scenario, "solverJobs": {"a4": job_id}},
        )

        assert response.status_code == 200, response.text
        assessment = response.json()["review"]["decisionReviews"][2]["solverAssessment"]
        assert assessment["status"] == expected_status
        assert assessment["actualFrequency"] == check_frequency
        assert assessment["thresholdMetadata"] == {
            "mixedThreshold": 0.05,
            "kind": "product_interpretation",
        }
        assert "evLoss" not in assessment
        findings = response.json()["review"]["priorityFindings"]
        if expected_status in {"rare", "absent"}:
            assert len(findings) == 1
            finding = findings[0]
            assert finding["actionId"] == "a4"
            assert finding["category"] == "solver_deviation"
            assert finding["mistakeTag"] == (
                "solver_rare_action"
                if expected_status == "rare"
                else "solver_absent_action"
            )
            assert finding["severity"] == "review"
            teaching = response.json()["review"]["decisionReviews"][2]["teaching"]
            assert finding["summary"] == teaching["summary"]
            assert finding["sourceKind"] == "aggregated_local"
            assert finding["provider"] == "local"
            assert finding["teacherVersion"] == "hand-review-aggregate-0.1"
            assert finding["promptVersion"] == "hand-review-aggregate-prompt-0.1"
            assert finding["degraded"] == teaching["degraded"]
            assert finding["degradationReason"] == teaching["degradationReason"]
        else:
            assert findings == []
    finally:
        queue.close()


def test_hand_review_rejects_a_solver_artifact_from_a_different_node():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    client = TestClient(
        create_app(config=AppConfig(), store=SQLiteStore(":memory:"), solver_queue=queue)
    )
    try:
        node_scenario = _flop_node_payload()
        submitted = client.post("/v1/solve/jobs", json={"scenario": node_scenario})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(job_id, status="solved", result=_solver_result(check_frequency=0.5))
        mismatched_scenario = _completed_checkdown_payload()
        mismatched_scenario["rangesBySeat"] = node_scenario["rangesBySeat"]
        mismatched_scenario["board"] = ["2d", "7d", "Jh", "9s", "3h"]

        response = client.post(
            "/v1/hand-reviews",
            json={"scenario": mismatched_scenario, "solverJobs": {"a4": job_id}},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "solver_artifact_mismatch"
        assert "review" not in response.json()  # mismatch cannot contaminate an action update
    finally:
        queue.close()


def test_hand_review_leaves_off_tree_and_missing_combo_actions_unscored():
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    client = TestClient(
        create_app(config=AppConfig(), store=SQLiteStore(":memory:"), solver_queue=queue)
    )
    try:
        node_scenario = _flop_node_payload()
        submitted = client.post("/v1/solve/jobs", json={"scenario": node_scenario})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        queue.finish(job_id, status="solved", result=_solver_result(check_frequency=0.5))

        off_tree = _flop_node_payload()
        off_tree["actionHistory"] = [
            *off_tree["actionHistory"],
            _action(4, 1, "bet", street="flop", amount=275, amount_type="by"),
        ]
        off_tree["decisionPoint"] = {"street": "flop", "actorSeat": 0, "afterSequence": 4}
        response = client.post(
            "/v1/hand-reviews",
            json={"scenario": off_tree, "solverJobs": {"a4": job_id}},
        )
        assert response.status_code == 200, response.text
        assessment = response.json()["review"]["decisionReviews"][2]["solverAssessment"]
        assert assessment["status"] == "unscored"
        assert assessment["source"] == "solver"
        assert assessment["actionMapping"]["offTree"] is True
        assert "evLoss" not in assessment

        unknown_combo = _completed_checkdown_payload(include_hole_cards=False)
        unknown_combo["rangesBySeat"] = node_scenario["rangesBySeat"]
        response = client.post(
            "/v1/hand-reviews",
            json={"scenario": unknown_combo, "solverJobs": {"a4": job_id}},
        )
        assert response.status_code == 200, response.text
        assessment = response.json()["review"]["decisionReviews"][2]["solverAssessment"]
        assert assessment["status"] == "unscored"
        assert "known concrete hole-card combo" in assessment["reason"]
    finally:
        queue.close()


def test_hand_review_leaves_preflop_and_non_hu_postflop_jobs_unscored():
    client = TestClient(create_app(store=SQLiteStore(":memory:")))
    preflop = _completed_checkdown_payload()
    response = client.post(
        "/v1/hand-reviews",
        json={"scenario": preflop, "solverJobs": {"a1": "not-looked-up"}},
    )
    assert response.status_code == 200, response.text
    assessment = response.json()["review"]["decisionReviews"][0]["solverAssessment"]
    assert assessment["status"] == "unscored"
    assert "postflop" in assessment["reason"]

    multiway = {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": 3,
        "smallBlind": 50,
        "bigBlind": 100,
        "buttonSeat": 0,
        "heroSeat": 0,
        "seats": [
            {"seatId": 0, "startingStack": 10000, "position": "button"},
            {"seatId": 1, "startingStack": 10000, "position": "small_blind"},
            {"seatId": 2, "startingStack": 10000, "position": "big_blind"},
        ],
        "knownHoleCardsBySeat": {"1": ["Qh", "Jc"]},
        "board": ["2c", "7d", "Th"],
        "actionHistory": [
            _action(1, 0, "call", amount=100, amount_type="cost"),
            _action(2, 1, "call", amount=50, amount_type="cost"),
            _action(3, 2, "check"),
            _action(4, 0, "deal_flop", street="flop"),
            _action(5, 1, "check", street="flop"),
        ],
        "decisionPoint": {"street": "flop", "actorSeat": 2, "afterSequence": 5},
        "assumptions": {},
    }
    response = client.post(
        "/v1/hand-reviews",
        json={"scenario": multiway, "solverJobs": {"a5": "not-looked-up"}},
    )
    assert response.status_code == 200, response.text
    assessment = response.json()["review"]["decisionReviews"][-1]["solverAssessment"]
    assert assessment["status"] == "unscored"
    assert "heads-up" in assessment["reason"]
