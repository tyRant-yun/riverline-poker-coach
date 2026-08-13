"""Focused acceptance tests for the polling-only continuous table API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence import SQLiteHandEventStore, SQLiteGameSessionStore
from poker_coach.simulator.continuous_table import ContinuousTableService


def _client(tmp_path):
    path = tmp_path / "continuous-table.sqlite3"
    service = ContinuousTableService(
        session_store=SQLiteGameSessionStore(path),
        event_store=SQLiteHandEventStore(path),
        metadata_path=path,
    )
    return TestClient(create_app(config=AppConfig(rate_limit_per_minute=0), table_service=service)), service


def _create(client, *, command_id="create-1", profile="balanced"):
    response = client.post(
        "/v1/tables",
        json={"schemaVersion": 1, "commandId": command_id, "seed": 24680, "botProfile": profile},
    )
    assert response.status_code == 200, response.text
    return response.json()["table"]


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
