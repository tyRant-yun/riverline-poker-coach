"""Black-box tests for the disposable session statistics read model."""

from __future__ import annotations

import json
import sqlite3

import pytest

from poker_coach.persistence.hand_event_store import SQLiteHandEventStore
from poker_coach.persistence.session_stats_store import SQLiteSessionStatsStore
from poker_coach.simulator.event_store import RawHandEventV1
from poker_coach.simulator.session_stats import (
    SessionStatsProjectionService,
    empty_session_stats,
)
from poker_coach.simulator.recovery import UnsupportedRecoverySchemaVersion


def _event(*, hand_id: str, sequence: int, payload: dict[str, object]) -> RawHandEventV1:
    return RawHandEventV1.from_json(
        json.dumps(
            {
                "schemaVersion": 1,
                "eventId": f"{hand_id}-evt-{sequence}",
                "handId": hand_id,
                "sequence": sequence,
                "timestamp": f"2026-08-12T00:00:{sequence:02d}Z",
                "source": "fixture",
                "provenance": {
                    "producer": "session-stats-tests",
                    "producerVersion": "1.0.0",
                    "correlationId": "session-stats",
                },
                "payload": payload,
            }
        )
    )


def _hand(*, hand_id: str, active_seats: tuple[int, ...], actions: list[tuple[int, str, int | None]], winners: tuple[int, ...]) -> tuple[RawHandEventV1, ...]:
    events = [
        _event(
            hand_id=hand_id,
            sequence=1,
            payload={
                "kind": "hand_started",
                "ruleset": "nlhe",
                "tableSize": 6,
                "buttonSeat": active_seats[0],
                "smallBlind": 50,
                "bigBlind": 100,
                "startingStacks": {str(seat): 10_000 for seat in range(6)},
                "activeSeatIds": list(active_seats),
                "rngSeed": 20260812,
            },
        )
    ]
    for sequence, (seat, action, amount) in enumerate(actions, start=2):
        semantics = {"fold": "none", "check": "none", "call": "cost", "bet": "by", "raise": "to"}[action]
        payload: dict[str, object] = {
            "kind": "action_taken",
            "street": "preflop",
            "actorSeat": seat,
            "action": action,
            "amountSemantics": semantics,
        }
        if amount is not None:
            payload["amount"] = amount
        events.append(_event(hand_id=hand_id, sequence=sequence, payload=payload))
    events.append(
        _event(
            hand_id=hand_id,
            sequence=len(events) + 1,
            payload={"kind": "hand_completed", "winnerSeats": list(winners), "payouts": {str(seat): 300 for seat in winners}},
        )
    )
    return tuple(events)


def _append(store: SQLiteHandEventStore, events: tuple[RawHandEventV1, ...]) -> None:
    store.append(hand_id=events[0].event.hand_id, expected_sequence=0, events=events)


def test_session_stats_accumulate_exact_preflop_rates_and_sparse_participants(tmp_path):
    path = tmp_path / "stats.sqlite3"
    events = SQLiteHandEventStore(path)
    first = _hand(
        hand_id="session-a:hand:1",
        active_seats=(0, 2, 5),
        actions=[(0, "call", 100), (2, "raise", 300), (5, "raise", 900), (0, "fold", None), (2, "call", 600)],
        winners=(5,),
    )
    second = _hand(
        hand_id="session-a:hand:2",
        active_seats=(0, 2),
        actions=[(0, "fold", None), (2, "check", None)],
        winners=(2,),
    )
    _append(events, first)
    _append(events, second)
    service = SessionStatsProjectionService(events, SQLiteSessionStatsStore(path))

    stats = service.apply_hand(session_id="session-a", hand_id="session-a:hand:1")
    stats = service.apply_hand(session_id="session-a", hand_id="session-a:hand:2")

    assert set(stats.by_seat) == {0, 2, 5}
    assert stats.by_seat[0].hands_dealt == 2
    assert stats.by_seat[0].hands_played == 2
    assert (stats.by_seat[0].vpip_actions, stats.by_seat[0].vpip_opportunities, stats.by_seat[0].vpip_rate) == (1, 2, 0.5)
    assert (stats.by_seat[2].pfr_actions, stats.by_seat[2].pfr_opportunities, stats.by_seat[2].pfr_rate) == (1, 2, 0.5)
    assert (stats.by_seat[5].three_bet_actions, stats.by_seat[5].three_bet_opportunities, stats.by_seat[5].three_bet_rate) == (1, 1, 1.0)
    assert stats.by_seat[5].hands_dealt == 1
    assert stats.by_seat[5].call_count == 0
    assert stats.by_seat[2].call_count == 1
    assert stats.by_seat[5].raise_count == 1
    assert stats.by_seat[5].won_hand_count == 1
    events.close()


def test_duplicate_delivery_restart_and_rebuild_are_idempotent_and_identical(tmp_path):
    path = tmp_path / "stats-rebuild.sqlite3"
    events = SQLiteHandEventStore(path)
    hand = _hand(
        hand_id="session-b:hand:1",
        active_seats=(0, 2, 5),
        actions=[(0, "call", 100), (2, "raise", 300), (5, "raise", 900), (0, "fold", None), (2, "fold", None)],
        winners=(5,),
    )
    _append(events, hand)
    store = SQLiteSessionStatsStore(path)
    first_service = SessionStatsProjectionService(events, store)
    first = first_service.apply_hand(session_id="session-b", hand_id=hand[0].event.hand_id)
    duplicate = first_service.apply_hand(session_id="session-b", hand_id=hand[0].event.hand_id)
    assert duplicate == first
    events.close()
    store.close()

    restarted_events = SQLiteHandEventStore(path)
    restarted_store = SQLiteSessionStatsStore(path)
    restarted = SessionStatsProjectionService(restarted_events, restarted_store)
    after_restart = restarted.apply_hand(session_id="session-b", hand_id=hand[0].event.hand_id)
    rebuilt = restarted.rebuild(session_id="session-b", hand_ids=(hand[0].event.hand_id,))

    assert after_restart == first
    assert rebuilt == first
    assert rebuilt.fingerprint == first.fingerprint
    restarted_events.close()
    restarted_store.close()


def test_session_stats_store_rejects_an_unknown_persisted_schema_version(tmp_path):
    path = tmp_path / "stats-unknown-schema.sqlite3"
    store = SQLiteSessionStatsStore(path)
    store.apply_hand("session-c", "hand-1", empty_session_stats("session-c"))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE session_stats_snapshots SET schema_version = 2 WHERE session_id = ?",
            ("session-c",),
        )

    with pytest.raises(UnsupportedRecoverySchemaVersion) as caught:
        store.load("session-c")

    assert caught.value.code == "unsupported_recovery_schema_version"
    store.close()
