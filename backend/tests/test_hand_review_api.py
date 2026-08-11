"""Black-box contract tests for the deterministic hand-review endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_coach.api import create_app
from poker_coach.persistence import SQLiteStore


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
        assert review["solverAssessment"]["status"] == "unscored"
        assert review["rangeUpdate"]["status"] == "unavailable"


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
