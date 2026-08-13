"""Focused acceptance tests for the polling-only continuous table API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence import SQLiteHandEventStore, SQLiteGameSessionStore
from poker_coach.simulator.continuous_table import ContinuousTableService
from poker_coach.simulator.contracts import (
    BotDecisionV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    SimulatorActionV1,
)


class _ShowdownBotRuntime:
    async def decide(self, provider, observation, *, time_budget_ms, rng_seed):
        del provider, time_budget_ms, rng_seed
        priority = (
            (SimulatorActionV1.FOLD,) if observation.observer_seat == 3 else ()
        ) + (
            SimulatorActionV1.CHECK,
            SimulatorActionV1.CALL,
            SimulatorActionV1.FOLD,
        )
        legal_by_action = {item.action: item for item in observation.legal_actions}
        legal = next(legal_by_action[action] for action in priority if action in legal_by_action)
        return BotDecisionV1(
            action=legal.action,
            amount=legal.min_amount,
            amount_semantics=legal.amount_semantics,
            provider="test-showdown",
            provider_version="1",
            latency_ms=0,
        )


class _FoldBotRuntime:
    async def decide(self, provider, observation, *, time_budget_ms, rng_seed):
        del provider, time_budget_ms, rng_seed
        legal_by_action = {item.action: item for item in observation.legal_actions}
        legal = next(
            legal_by_action[action]
            for action in (SimulatorActionV1.FOLD, SimulatorActionV1.CHECK, SimulatorActionV1.CALL)
            if action in legal_by_action
        )
        return BotDecisionV1(
            action=legal.action,
            amount=legal.min_amount,
            amount_semantics=legal.amount_semantics,
            provider="test-fold",
            provider_version="1",
            latency_ms=0,
        )


def _client(tmp_path, *, seed_source=None, bot_runtime=None):
    path = tmp_path / "continuous-table.sqlite3"
    service = ContinuousTableService(
        session_store=SQLiteGameSessionStore(path),
        event_store=SQLiteHandEventStore(path),
        metadata_path=path,
        seed_source=seed_source,
        bot_runtime=bot_runtime,
    )
    return TestClient(create_app(config=AppConfig(rate_limit_per_minute=0), table_service=service)), service


def _create(client, *, command_id="create-1", profile="balanced", seed=24680):
    payload = {"schemaVersion": 1, "commandId": command_id, "botProfile": profile}
    if seed is not None:
        payload["seed"] = seed
    response = client.post(
        "/v1/tables",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()["table"]


def _opening_identity(service, hand_id):
    events = tuple(item.event for item in service.event_store.read(hand_id))
    started = events[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    hole_cards = tuple(
        (event.payload.seat_id, event.payload.cards)
        for event in events
        if isinstance(event.payload, HoleCardsRecordedPayloadV1)
    )
    return started.rng_seed, hole_cards


def _hero_action(client, table, command_id):
    legal = table["heroLegalActions"][0]
    payload = {
        "schemaVersion": 1,
        "commandId": command_id,
        "handId": table["handId"],
        "expectedRevision": table["revision"],
        "action": legal["action"],
        "amountSemantics": legal["amountSemantics"],
    }
    if legal.get("minAmount") is not None:
        payload["amount"] = legal["minAmount"]
    return client.post(f"/v1/tables/{table['sessionId']}/actions", json=payload)


def _passive_hero_action(client, table, command_id):
    legal_by_action = {item["action"]: item for item in table["heroLegalActions"]}
    legal = next(legal_by_action[action] for action in ("check", "call", "fold") if action in legal_by_action)
    payload = {
        "schemaVersion": 1,
        "commandId": command_id,
        "handId": table["handId"],
        "expectedRevision": table["revision"],
        "action": legal["action"],
        "amountSemantics": legal["amountSemantics"],
    }
    if legal.get("minAmount") is not None:
        payload["amount"] = legal["minAmount"]
    return client.post(f"/v1/tables/{table['sessionId']}/actions", json=payload)


def test_create_bots_advance_hero_action_complete_and_next_hand(tmp_path):
    client, service = _client(tmp_path)
    table = _create(client)

    assert table["handSequence"] == 1
    assert table["heroSeat"] == 0
    assert table["currentActor"] == 0
    assert len(table["actionHistory"]) >= 2  # blinds plus bot decisions before hero
    assert all("holeCards" not in seat for seat in table["seats"])
    assert len(table["heroHoleCards"]) == 2

    for turn in range(30):
        if table["handComplete"]:
            break
        response = _hero_action(client, table, f"hero-{turn}")
        assert response.status_code == 200, response.text
        table = response.json()["table"]
    assert table["handComplete"] is True
    assert table["result"] is not None

    response = client.post(
        f"/v1/tables/{table['sessionId']}/hands",
        json={"schemaVersion": 1, "commandId": "next-1", "expectedRevision": table["revision"]},
    )
    assert response.status_code == 200, response.text
    next_table = response.json()["table"]
    assert next_table["handSequence"] == 2
    assert next_table["buttonSeat"] == 1
    service.close()


def test_default_consecutive_hands_use_fresh_entropy_and_explicit_seed_replays(tmp_path):
    entropy_calls = 0

    def seed_source():
        nonlocal entropy_calls
        entropy_calls += 1
        return 700_000

    client, service = _client(tmp_path, seed_source=seed_source)
    table = _create(client, seed=None)
    first_seed, first_holes = _opening_identity(service, table["handId"])

    for turn in range(30):
        if table["handComplete"]:
            break
        response = _hero_action(client, table, f"fresh-{turn}")
        assert response.status_code == 200, response.text
        table = response.json()["table"]
    response = client.post(
        f"/v1/tables/{table['sessionId']}/hands",
        json={"schemaVersion": 1, "commandId": "fresh-next", "expectedRevision": table["revision"]},
    )
    assert response.status_code == 200, response.text
    next_table = response.json()["table"]
    second_seed, second_holes = _opening_identity(service, next_table["handId"])

    assert entropy_calls == 1
    assert (first_seed, second_seed) == (700_000, 700_001)
    assert first_holes != second_holes

    explicit_a = _create(client, command_id="explicit-a", seed=24680)
    explicit_b = _create(client, command_id="explicit-b", seed=24680)
    assert _opening_identity(service, explicit_a["handId"])[1] == _opening_identity(
        service, explicit_b["handId"]
    )[1]
    assert entropy_calls == 1
    service.close()


def test_terminal_showdown_reveals_only_live_contenders(tmp_path):
    client, service = _client(tmp_path, bot_runtime=_ShowdownBotRuntime())
    table = _create(client)
    assert all("revealedHoleCards" not in seat for seat in table["seats"])

    for turn in range(30):
        if table["handComplete"]:
            break
        response = _passive_hero_action(client, table, f"showdown-{turn}")
        assert response.status_code == 200, response.text
        table = response.json()["table"]

    assert table["handComplete"] is True
    assert len(table["board"]) == 5
    recorded = dict(_opening_identity(service, table["handId"])[1])
    folded_seats = {seat["seatId"] for seat in table["seats"] if seat["status"] == "folded"}
    assert folded_seats == {3}
    assert {
        seat["seatId"]: tuple(seat["revealedHoleCards"])
        for seat in table["seats"]
        if "revealedHoleCards" in seat
    } == {seat_id: cards for seat_id, cards in recorded.items() if seat_id not in folded_seats}
    service.close()


def test_terminal_uncontested_hand_never_reveals_opponent_cards(tmp_path):
    client, service = _client(tmp_path, bot_runtime=_FoldBotRuntime())
    table = _create(client)
    response = client.post(
        f"/v1/tables/{table['sessionId']}/actions",
        json={
            "schemaVersion": 1,
            "commandId": "hero-fold",
            "handId": table["handId"],
            "expectedRevision": table["revision"],
            "action": "fold",
            "amountSemantics": "none",
        },
    )
    assert response.status_code == 200, response.text
    completed = response.json()["table"]
    assert completed["handComplete"] is True
    assert sum(seat["status"] != "folded" for seat in completed["seats"]) == 1
    assert all("revealedHoleCards" not in seat for seat in completed["seats"])
    service.close()


def test_three_hands_reconnect_idempotency_and_information_isolation(tmp_path):
    client, service = _client(tmp_path)
    table = _create(client, profile="balanced")
    session_id = table["sessionId"]
    retry_next_payload = None

    for hand in range(3):
        for turn in range(30):
            if table["handComplete"]:
                break
            response = _hero_action(client, table, f"h{hand}-a{turn}")
            assert response.status_code == 200, response.text
            table = response.json()["table"]
        assert table["handComplete"]
        if hand < 2:
            next_payload = {"schemaVersion": 1, "commandId": f"next-{hand}", "expectedRevision": table["revision"]}
            if hand == 1:
                retry_next_payload = next_payload
            response = client.post(
                f"/v1/tables/{session_id}/hands",
                json=next_payload,
            )
            assert response.status_code == 200, response.text
            table = response.json()["table"]

    before = client.get(f"/v1/tables/{session_id}").json()["table"]
    duplicate = client.post(
        f"/v1/tables/{session_id}/hands",
        json=retry_next_payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent"] is True
    assert duplicate.json()["table"] == before

    service.close()
    rebuilt = ContinuousTableService.from_sqlite_path(service.path)
    rebuilt_client = TestClient(create_app(config=AppConfig(rate_limit_per_minute=0), table_service=rebuilt))
    after = rebuilt_client.get(f"/v1/tables/{session_id}").json()["table"]
    assert after["fingerprint"] == before["fingerprint"]
    assert after["handSequence"] == 3
    assert after["buttonSeat"] == 3
    assert "rngSeed" not in str(after)
    assert "knownHoleCards" not in str(after)
    rebuilt.close()


def test_profiles_conflicts_and_bot_fallback_are_stable(tmp_path):
    client, service = _client(tmp_path)
    for profile in ("cautious", "balanced", "aggressive"):
        table = _create(client, command_id=f"create-{profile}", profile=profile)
        assert {item["profileId"] for item in table["botDecisionProvenance"]} == {profile}

    table = _create(client, command_id="create-conflict")
    duplicate = _hero_action(client, table, "same-hero-command")
    assert duplicate.status_code == 200
    replay = client.post(
        f"/v1/tables/{table['sessionId']}/actions",
        json={
            "schemaVersion": 1, "commandId": "same-hero-command", "handId": table["handId"],
            "expectedRevision": table["revision"], "action": "fold", "amountSemantics": "none",
        },
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "command_id_conflict"

    stale = client.post(
        f"/v1/tables/{table['sessionId']}/actions",
        json={
            "schemaVersion": 1, "commandId": "stale", "handId": table["handId"],
            "expectedRevision": 0, "action": "fold", "amountSemantics": "none",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    service.close()


def test_active_hand_stacks_follow_pokerkit_and_survive_reconnect(tmp_path):
    client, service = _client(tmp_path)
    table = _create(client)
    session_id = table["sessionId"]

    assert any(seat["stack"] < 10_000 for seat in table["seats"])
    assert {seat["seatId"]: seat["stack"] for seat in table["seats"]} != {
        seat.seat_id: seat.stack for seat in service.session_store.load(session_id).session.topology.seats
    }

    service.close()
    rebuilt = ContinuousTableService.from_sqlite_path(service.path)
    rebuilt_client = TestClient(
        create_app(config=AppConfig(rate_limit_per_minute=0), table_service=rebuilt)
    )
    after = rebuilt_client.get(f"/v1/tables/{session_id}").json()["table"]
    assert [seat["stack"] for seat in after["seats"]] == [
        seat["stack"] for seat in table["seats"]
    ]

    while not table["handComplete"]:
        response = _hero_action(rebuilt_client, table, f"settle-{table['revision']}")
        assert response.status_code == 200, response.text
        table = response.json()["table"]
    assert [seat["stack"] for seat in table["seats"]] == [
        seat.stack for seat in rebuilt.session_store.load(session_id).session.topology.seats
    ]
    rebuilt.close()


def test_table_insights_are_read_only_and_never_expose_opponent_cards(tmp_path):
    client, service = _client(tmp_path)
    table = _create(client)
    response = client.get(f"/v1/tables/{table['sessionId']}/insights")
    assert response.status_code == 200, response.text
    insights = response.json()["insights"]
    assert insights["advisor"]["available"] is True
    assert all(item["seatId"] != table["heroSeat"] for item in insights["seatBeliefs"])
    assert "holeCards" not in str(insights)
    assert insights["stats"]["unavailableReason"] == "stats_not_ready"
    service.close()


def test_completed_table_materializes_one_safe_review_and_reconnects(tmp_path):
    client, service = _client(tmp_path)
    table = _create(client)
    while not table["handComplete"]:
        response = _hero_action(client, table, f"review-{table['revision']}")
        assert response.status_code == 200, response.text
        table = response.json()["table"]
    response = client.get(f"/v1/tables/{table['sessionId']}/reviews/{table['handId']}")
    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["heroSeat"] == table["heroSeat"]
    assert "holeCards" not in str(review)
    assert "payout" not in str(review).lower()
    duplicate = client.get(f"/v1/tables/{table['sessionId']}/reviews")
    assert len(duplicate.json()["reviews"]) == 1
    service.close()
