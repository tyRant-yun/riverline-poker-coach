"""Golden PHH exchange evidence for the authoritative simulator seam."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poker_coach.persistence import SQLiteHandEventStore
from poker_coach.simulator import (
    GameOrchestrator,
    GameSession,
    OpenHandCommandV1,
    PlayerActionCommandV1,
    SessionSeatV1,
)
from poker_coach.simulator.phh import HandHistoryCodec, PhhCodecError


def _session(*, stacks=(10_000,) * 6, sitting_out=()):
    return GameSession.model_validate({
        "sessionId": "phh-session",
        "topology": {"seats": [
            SessionSeatV1(seat_id=seat, stack=stack, sitting_out=seat in sitting_out).to_dict()
            for seat, stack in enumerate(stacks)
        ]},
        "buttonSeat": next(seat for seat, stack in enumerate(stacks) if stack > 0),
    }).start_next_hand()


def _events(tmp_path, *, stacks=(10_000,) * 6, sitting_out=(), actions=()):
    session = _session(stacks=stacks, sitting_out=sitting_out)
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "phh.sqlite3")
    orchestrator = GameOrchestrator(store, clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc))
    result = orchestrator.open_hand(session, OpenHandCommandV1(
        session_id=session.session_id, hand_id=session.active_hand.hand_id,
        command_id="open", expected_sequence=0, rng_seed=20260812,
    ))
    for index, (seat, action, amount, semantics) in enumerate(actions, start=1):
        result = orchestrator.execute(session, PlayerActionCommandV1(
            session_id=session.session_id, hand_id=session.active_hand.hand_id,
            command_id=f"action-{index}", expected_sequence=result.replayed_hand.state.applied_sequence,
            actor_seat=seat, action=action, amount=amount, amount_semantics=semantics,
        ))
    events = tuple(item.event for item in store.read(session.active_hand.hand_id))
    store.close()
    return events, result.replayed_hand.state


@pytest.mark.parametrize(
    "stacks,sitting_out,actions",
    [
        ((10_000,) * 6, (), (
            (3, "fold", None, "none"), (4, "fold", None, "none"), (5, "fold", None, "none"),
            (0, "call", 100, "cost"), (1, "call", 50, "cost"), (2, "check", None, "none"),
            (1, "check", None, "none"), (2, "check", None, "none"), (0, "check", None, "none"),
            (1, "check", None, "none"), (2, "check", None, "none"), (0, "check", None, "none"),
            (1, "check", None, "none"), (2, "check", None, "none"), (0, "check", None, "none"),
        )),
        ((0, 20_000, 10_000, 10_000, 10_000, 10_000), (), (
            (4, "fold", None, "none"), (5, "fold", None, "none"), (1, "fold", None, "none"), (2, "fold", None, "none"),
        )),
        ((3_000, 2_000, 5_000, 10_000, 10_000, 10_000), (), (
            (3, "fold", None, "none"), (4, "fold", None, "none"), (5, "fold", None, "none"),
            (0, "raise", 3_000, "to"), (1, "call", 1_950, "cost"), (2, "call", 2_900, "cost"),
        )),
        ((10_000,) * 6, (1, 2), (
            (5, "fold", None, "none"), (0, "fold", None, "none"), (3, "fold", None, "none"),
        )),
    ],
    ids=["standard-6max", "post-bust-sparse", "all-in-side-pot", "fold-completion"],
)
def test_authoritative_events_phh_round_trip_preserves_public_replay_facts(tmp_path, stacks, sitting_out, actions):
    events, expected = _events(tmp_path, stacks=stacks, sitting_out=sitting_out, actions=actions)
    codec = HandHistoryCodec()
    text = codec.export(events)
    imported = codec.import_phh(text, imported_at=datetime(2026, 8, 12, tzinfo=timezone.utc))
    from poker_coach.simulator import replay_hand
    actual = replay_hand(imported.events).state

    assert actual.board == expected.board
    assert actual.stacks == expected.stacks
    assert actual.winner_seats == expected.winner_seats
    assert actual.payouts == expected.payouts
    assert actual.fingerprint == expected.fingerprint
    assert [event.source for event in imported.events] == [event.source for event in events]


def test_import_rejects_invalid_or_information_insufficient_phh():
    codec = HandHistoryCodec()
    with pytest.raises(PhhCodecError) as malformed:
        codec.import_phh("variant = 'NT'\nactions = ['p1 f']")
    assert malformed.value.code == "invalid_phh"

    incomplete_showdown = """variant = 'NT'
antes = [0, 0]
blinds_or_straddles = [50, 100]
min_bet = 100
starting_stacks = [1000, 1000]
actions = ['p1 cbr 1000', 'p2 cc', 'd db AsKdQh', 'd db Jc', 'd db Ts']
"""
    with pytest.raises(PhhCodecError) as missing:
        codec.import_phh(incomplete_showdown, hand_id="missing-cards")
    assert missing.value.code in {"invalid_phh", "insufficient_hole_cards", "authoritative_replay_rejected"}
