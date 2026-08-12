"""Public-seam tests for the F1-03 authoritative hand orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poker_coach.persistence import SQLiteHandEventStore
from poker_coach.simulator import (
    AmountSemanticsV1,
    ExpectedSequenceConflict,
    GameCommandError,
    GameOrchestrator,
    GameSession,
    OpenHandCommandV1,
    PlayerActionCommandV1,
    RawHandEventV1,
    SessionLifecycleError,
    SessionSeatV1,
    SimulatorActionV1,
    replay_hand,
)


def _opened_session() -> GameSession:
    return GameSession.create(
        session_id="session-f1-03",
        seats=tuple(
            SessionSeatV1(seat_id=seat_id, stack=10_000)
            for seat_id in range(6)
        ),
    ).start_next_hand()


def _opened_session_with_stacks(stacks: tuple[int, ...]) -> GameSession:
    return GameSession.model_validate(
        {
            "sessionId": "session-f1-03",
            "topology": {
                "seats": [
                    {"seatId": seat_id, "stack": stack}
                    for seat_id, stack in enumerate(stacks)
                ]
            },
            "buttonSeat": 0,
        }
    ).start_next_hand()


def _opened_session_with_sitting_out(*seat_ids: int) -> GameSession:
    return GameSession.create(
        session_id="session-f1-03",
        seats=tuple(
            SessionSeatV1(
                seat_id=seat_id,
                stack=10_000,
                sitting_out=seat_id in seat_ids,
            )
            for seat_id in range(6)
        ),
    ).start_next_hand()


def test_open_hand_persists_seeded_pokerkit_validated_opening_facts(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "orchestrator.sqlite3")
    orchestrator = GameOrchestrator(
        store,
        clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc),
    )

    result = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    stored = tuple(item.event for item in store.read(session.active_hand.hand_id))
    assert result.appended_events == stored
    assert [event.payload.kind for event in stored] == [
        "hand_started",
        *("hole_cards_recorded" for _ in range(6)),
    ]
    assert all(event.source.value == "game_orchestrator" for event in stored)
    assert all(
        event.provenance.causation_id == "open-command-1" for event in stored
    )
    assert stored[0].payload.rng_seed == 20260812
    assert [event.payload.cards for event in stored[1:]] == [
        ("Js", "2h"),
        ("2s", "Kd"),
        ("3c", "8h"),
        ("6s", "Jd"),
        ("Ac", "Ad"),
        ("Qc", "5s"),
    ]
    assert replay_hand(stored).state.hand_in_progress is True
    assert replay_hand(stored).state.pot == 150
    store.close()


def test_sparse_active_seats_are_rejected_at_the_frozen_hand_event_v1_boundary(
    tmp_path,
):
    session = _opened_session_with_sitting_out(1, 2)
    assert session.active_hand is not None
    assert tuple(seat.seat_id for seat in session.active_hand.seats) == (0, 3, 4, 5)
    store = SQLiteHandEventStore(tmp_path / "sparse-active.sqlite3")

    with pytest.raises(SessionLifecycleError) as caught:
        GameOrchestrator(store).open_hand(
            session,
            OpenHandCommandV1(
                session_id=session.session_id,
                hand_id=session.active_hand.hand_id,
                command_id="sparse-open",
                expected_sequence=0,
                rng_seed=20260812,
            ),
        )

    assert caught.value.code == "unsupported_active_topology"
    assert store.read(session.active_hand.hand_id) == ()
    store.close()


def test_command_contracts_are_versioned_and_carry_identity_sequence_actor_and_parameters():
    opened = _opened_session()
    assert opened.active_hand is not None
    opening = OpenHandCommandV1(
        session_id=opened.session_id,
        hand_id=opened.active_hand.hand_id,
        command_id="open-command-1",
        expected_sequence=0,
        rng_seed=20260812,
    )
    action = PlayerActionCommandV1(
        session_id=opened.session_id,
        hand_id=opened.active_hand.hand_id,
        command_id="action-command-1",
        expected_sequence=7,
        actor_seat=3,
        action="raise",
        amount=200,
        amount_semantics="to",
    )

    assert opening.schema_version == 1
    assert opening.actor == "game_orchestrator"
    assert opening.rng_seed == 20260812
    assert action.schema_version == 1
    assert action.actor_seat == 3
    assert action.amount == 200


def test_session_hand_and_expected_sequence_mismatches_have_stable_failures(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "ownership.sqlite3")
    opened = GameOrchestrator(store).open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    base = PlayerActionCommandV1(
        session_id=session.session_id,
        hand_id=hand_id,
        command_id="ownership-action",
        expected_sequence=opened.replayed_hand.state.applied_sequence,
        actor_seat=3,
        action="fold",
        amount_semantics="none",
    )

    with pytest.raises(SessionLifecycleError) as session_error:
        GameOrchestrator(store).execute(
            session, base.model_copy(update={"session_id": "other-session"})
        )
    assert session_error.value.code == "session_ownership_mismatch"

    with pytest.raises(SessionLifecycleError) as hand_error:
        GameOrchestrator(store).execute(
            session, base.model_copy(update={"hand_id": "session-f1-03:hand:99"})
        )
    assert hand_error.value.code == "hand_ownership_mismatch"

    with pytest.raises(ExpectedSequenceConflict) as sequence_error:
        GameOrchestrator(store).execute(
            session, base.model_copy(update={"expected_sequence": 6})
        )
    assert sequence_error.value.actual_sequence == 7
    assert len(store.read(hand_id)) == 7
    store.close()


def test_player_action_rebuilds_durable_state_before_atomic_append(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "action.sqlite3")
    orchestrator = GameOrchestrator(
        store,
        clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    opened = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    acted = orchestrator.execute(
        session,
        PlayerActionCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="action-command-1",
            expected_sequence=opened.replayed_hand.state.applied_sequence,
            actor_seat=3,
            action=SimulatorActionV1.FOLD,
            amount_semantics=AmountSemanticsV1.NONE,
        ),
    )

    assert [event.payload.kind for event in acted.appended_events] == ["action_taken"]
    action = acted.appended_events[0].payload
    assert action.actor_seat == 3
    assert action.action is SimulatorActionV1.FOLD
    stored = tuple(item.event for item in store.read(session.active_hand.hand_id))
    assert [event.sequence for event in stored] == list(range(1, 9))
    assert replay_hand(stored).state.folded_seats == (3,)
    store.close()


def test_non_current_actor_is_rejected_without_appending(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "wrong-actor.sqlite3")
    orchestrator = GameOrchestrator(store)
    opened = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    with pytest.raises(GameCommandError) as caught:
        orchestrator.execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=session.active_hand.hand_id,
                command_id="wrong-actor-command",
                expected_sequence=opened.replayed_hand.state.applied_sequence,
                actor_seat=4,
                action="fold",
                amount_semantics="none",
            ),
        )

    assert caught.value.code == "wrong_actor"
    assert len(store.read(session.active_hand.hand_id)) == 7
    store.close()


@pytest.mark.parametrize(
    ("action", "amount", "amount_semantics", "expected_code"),
    [
        ("check", None, "none", "action_not_legal"),
        ("call", 99, "cost", "amount_out_of_bounds"),
        ("bet", 100, "by", "action_not_legal"),
        ("raise", 199, "to", "amount_out_of_bounds"),
        ("raise", 10_001, "to", "amount_out_of_bounds"),
    ],
)
def test_illegal_action_and_amount_boundaries_fail_clearly_without_append(
    tmp_path, action, amount, amount_semantics, expected_code
):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / f"illegal-{action}-{amount}.sqlite3")
    orchestrator = GameOrchestrator(store)
    opened = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    with pytest.raises(GameCommandError) as caught:
        orchestrator.execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=session.active_hand.hand_id,
                command_id=f"illegal-{action}-{amount}",
                expected_sequence=opened.replayed_hand.state.applied_sequence,
                actor_seat=3,
                action=action,
                amount=amount,
                amount_semantics=amount_semantics,
            ),
        )

    assert caught.value.code == expected_code
    assert len(store.read(session.active_hand.hand_id)) == 7
    store.close()


def test_terminal_action_appends_settlement_once_and_updates_session_stacks(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "settlement.sqlite3")
    orchestrator = GameOrchestrator(store)
    result = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    for index, actor in enumerate((3, 4, 5, 0, 1), start=1):
        result = orchestrator.execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=hand_id,
                command_id=f"fold-command-{index}",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=actor,
                action="fold",
                amount_semantics="none",
            ),
        )

    assert [event.payload.kind for event in result.appended_events] == [
        "action_taken",
        "hand_completed",
    ]
    assert result.replayed_hand.state.winner_seats == (2,)
    assert result.replayed_hand.state.payouts == {2: 50}
    assert sum(result.replayed_hand.state.stacks.values()) == 60_000
    assert result.session.active_hand is None
    assert result.session.completed_hand_ids == (hand_id,)
    assert result.session.topology.seats[1].stack == 9_950
    assert result.session.topology.seats[2].stack == 10_050
    stored = tuple(item.event for item in store.read(hand_id))
    assert sum(event.payload.kind == "hand_completed" for event in stored) == 1
    assert replay_hand(stored).state.fingerprint == result.replayed_hand.state.fingerprint
    store.close()


def _run_seeded_checkdown(path):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(path)
    orchestrator = GameOrchestrator(
        store,
        clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    result = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    actions = (
        (3, "fold", None, "none"),
        (4, "fold", None, "none"),
        (5, "fold", None, "none"),
        (0, "call", 100, "cost"),
        (1, "call", 50, "cost"),
        (2, "check", None, "none"),
        (1, "check", None, "none"),
        (2, "check", None, "none"),
        (0, "check", None, "none"),
        (1, "check", None, "none"),
        (2, "check", None, "none"),
        (0, "check", None, "none"),
        (1, "check", None, "none"),
        (2, "check", None, "none"),
        (0, "check", None, "none"),
    )
    batches = []
    for index, (actor, action, amount, semantics) in enumerate(actions, start=1):
        result = orchestrator.execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=session.active_hand.hand_id,
                command_id=f"action-command-{index}",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=actor,
                action=action,
                amount=amount,
                amount_semantics=semantics,
            ),
        )
        batches.append(tuple(event.payload.kind for event in result.appended_events))
    events = tuple(item.event for item in store.read(session.active_hand.hand_id))
    store.close()
    return result, batches, events


def test_fixed_seed_full_lifecycle_auto_deals_and_replays_deterministically(tmp_path):
    first, first_batches, first_events = _run_seeded_checkdown(tmp_path / "first.sqlite3")
    second, second_batches, second_events = _run_seeded_checkdown(tmp_path / "second.sqlite3")

    assert first_batches[5] == ("action_taken", "board_dealt")
    assert first_batches[8] == ("action_taken", "board_dealt")
    assert first_batches[11] == ("action_taken", "board_dealt")
    assert first_batches[-1] == ("action_taken", "hand_completed")
    assert first.replayed_hand.state.board == second.replayed_hand.state.board
    assert first.replayed_hand.state.board == ("4s", "9d", "7h", "Ts", "Ks")
    assert first.replayed_hand.state.stacks == second.replayed_hand.state.stacks
    assert first.replayed_hand.state.fingerprint == second.replayed_hand.state.fingerprint
    assert [event.to_json() for event in first_events] == [
        event.to_json() for event in second_events
    ]
    assert first.replayed_hand.state.hand_in_progress is False
    assert sum(first.replayed_hand.state.stacks.values()) == 60_000


def test_all_in_side_pot_path_conserves_chips_through_pokerkit_settlement(tmp_path):
    session = _opened_session_with_stacks((3_000, 2_000, 5_000, 10_000, 10_000, 10_000))
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "side-pot.sqlite3")
    orchestrator = GameOrchestrator(store)
    result = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    actions = (
        (3, "fold", None, "none"),
        (4, "fold", None, "none"),
        (5, "fold", None, "none"),
        (0, "raise", 3_000, "to"),
        (1, "call", 1_950, "cost"),
        (2, "call", 2_900, "cost"),
    )
    for index, (actor, action, amount, semantics) in enumerate(actions, start=1):
        result = orchestrator.execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=hand_id,
                command_id=f"side-pot-command-{index}",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=actor,
                action=action,
                amount=amount,
                amount_semantics=semantics,
            ),
        )

    assert [event.payload.kind for event in result.appended_events] == [
        "action_taken",
        "board_dealt",
        "board_dealt",
        "board_dealt",
        "hand_completed",
    ]
    assert result.replayed_hand.state.hand_in_progress is False
    assert len(result.replayed_hand.state.board) == 5
    assert sum(result.replayed_hand.state.stacks.values()) == 40_000
    assert result.replayed_hand.state.payouts
    assert sum(result.replayed_hand.state.payouts.values()) == 8_000
    stored = tuple(item.event for item in store.read(hand_id))
    assert replay_hand(stored).state.fingerprint == result.replayed_hand.state.fingerprint
    store.close()


def test_duplicate_command_id_is_idempotent_but_conflicting_reuse_is_rejected(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "idempotency.sqlite3")
    orchestrator = GameOrchestrator(store)
    opened = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    command = PlayerActionCommandV1(
        session_id=session.session_id,
        hand_id=hand_id,
        command_id="idempotent-action",
        expected_sequence=opened.replayed_hand.state.applied_sequence,
        actor_seat=3,
        action="fold",
        amount_semantics="none",
    )
    first = orchestrator.execute(session, command)

    duplicate = GameOrchestrator(store).execute(session, command)

    assert duplicate.idempotent is True
    assert duplicate.appended_events == ()
    assert duplicate.replayed_hand.state.fingerprint == first.replayed_hand.state.fingerprint
    assert len(store.read(hand_id)) == 8

    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(store).execute(
            session,
            command.model_copy(
                update={
                    "action": SimulatorActionV1.CALL,
                    "amount": 100,
                    "amount_semantics": AmountSemanticsV1.COST,
                }
            ),
        )
    assert caught.value.code == "command_id_conflict"
    assert len(store.read(hand_id)) == 8
    store.close()


def test_open_command_retry_is_idempotent_and_seed_conflict_is_explicit(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    store = SQLiteHandEventStore(tmp_path / "open-idempotency.sqlite3")
    command = OpenHandCommandV1(
        session_id=session.session_id,
        hand_id=session.active_hand.hand_id,
        command_id="open-command-1",
        expected_sequence=0,
        rng_seed=20260812,
    )
    first = GameOrchestrator(store).open_hand(session, command)

    duplicate = GameOrchestrator(store).open_hand(session, command)

    assert duplicate.idempotent is True
    assert duplicate.appended_events == ()
    assert duplicate.replayed_hand.state.fingerprint == first.replayed_hand.state.fingerprint
    assert len(store.read(session.active_hand.hand_id)) == 7

    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(store).open_hand(
            session, command.model_copy(update={"rng_seed": 20260813})
        )
    assert caught.value.code == "command_id_conflict"
    assert len(store.read(session.active_hand.hand_id)) == 7
    store.close()


def test_open_retry_rejects_durable_hole_cards_that_do_not_match_the_seed(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    source = SQLiteHandEventStore(tmp_path / "seed-hole-source.sqlite3")
    command = OpenHandCommandV1(
        session_id=session.session_id,
        hand_id=session.active_hand.hand_id,
        command_id="open-command-1",
        expected_sequence=0,
        rng_seed=20260812,
    )
    GameOrchestrator(source).open_hand(session, command)
    events = [item.event for item in source.read(session.active_hand.hand_id)]
    source.close()
    first_cards = events[1].payload.cards
    second_cards = events[2].payload.cards
    events[1] = events[1].model_copy(
        update={"payload": events[1].payload.model_copy(update={"cards": second_cards})}
    )
    events[2] = events[2].model_copy(
        update={"payload": events[2].payload.model_copy(update={"cards": first_cards})}
    )
    tampered = SQLiteHandEventStore(tmp_path / "seed-hole-tampered.sqlite3")
    tampered.append(
        hand_id=session.active_hand.hand_id,
        expected_sequence=0,
        events=tuple(RawHandEventV1.from_event(event) for event in events),
    )

    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(tampered).open_hand(session, command)

    assert caught.value.code == "seed_provenance_mismatch"
    assert len(tampered.read(session.active_hand.hand_id)) == 7
    tampered.close()


def test_restart_rejects_durable_board_cards_that_do_not_match_the_seed(tmp_path):
    result, _, original = _run_seeded_checkdown(tmp_path / "seed-board-source.sqlite3")
    session = _opened_session()
    assert session.active_hand is not None
    events = list(original)
    board_index = next(
        index for index, event in enumerate(events) if event.payload.kind == "board_dealt"
    )
    events[board_index] = events[board_index].model_copy(
        update={
            "payload": events[board_index].payload.model_copy(
                update={"cards": ("4c", "9d", "7h")}
            )
        }
    )
    assert replay_hand(events).state.hand_in_progress is False
    tampered = SQLiteHandEventStore(tmp_path / "seed-board-tampered.sqlite3")
    tampered.append(
        hand_id=session.active_hand.hand_id,
        expected_sequence=0,
        events=tuple(RawHandEventV1.from_event(event) for event in events),
    )

    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(tampered).execute(
            session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=session.active_hand.hand_id,
                command_id="after-restart",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=0,
                action="check",
                amount_semantics="none",
            ),
        )

    assert caught.value.code == "seed_provenance_mismatch"
    assert len(tampered.read(session.active_hand.hand_id)) == len(events)
    tampered.close()


def test_second_open_command_observes_durable_head_instead_of_overwriting_hand(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "second-open.sqlite3")
    first = OpenHandCommandV1(
        session_id=session.session_id,
        hand_id=hand_id,
        command_id="open-command-1",
        expected_sequence=0,
        rng_seed=20260812,
    )
    GameOrchestrator(store).open_hand(session, first)

    with pytest.raises(ExpectedSequenceConflict) as caught:
        GameOrchestrator(store).open_hand(
            session, first.model_copy(update={"command_id": "open-command-2"})
        )

    assert caught.value.actual_sequence == 7
    assert len(store.read(hand_id)) == 7
    store.close()


class _ConflictInjectingStore:
    def __init__(self, delegate, *, preserve_command_id: bool):
        self.delegate = delegate
        self.preserve_command_id = preserve_command_id
        self.append_calls = 0

    def read(self, hand_id):
        return self.delegate.read(hand_id)

    def append(self, *, hand_id, expected_sequence, events):
        self.append_calls += 1
        winner = tuple(events)
        if not self.preserve_command_id:
            winner = tuple(
                RawHandEventV1.from_event(
                    item.event.model_copy(
                        update={
                            "event_id": f"winner-{item.event.event_id}",
                            "provenance": item.event.provenance.model_copy(
                                update={"causation_id": "winning-command"}
                            ),
                        }
                    )
                )
                for item in winner
            )
        result = self.delegate.append(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=winner,
        )
        raise ExpectedSequenceConflict(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            actual_sequence=result.last_sequence,
        )


class _CompletedOpenConflictStore:
    def __init__(self, delegate, completed_events):
        self.delegate = delegate
        self.completed_events = completed_events
        self.append_calls = 0

    def read(self, hand_id):
        return self.delegate.read(hand_id)

    def append(self, *, hand_id, expected_sequence, events):
        self.append_calls += 1
        result = self.delegate.append(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=tuple(
                RawHandEventV1.from_event(event) for event in self.completed_events
            ),
        )
        raise ExpectedSequenceConflict(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            actual_sequence=result.last_sequence,
        )


@pytest.mark.parametrize("preserve_command_id", (True, False))
def test_append_conflict_rereads_once_and_never_blindly_retries_non_idempotent_action(
    tmp_path, preserve_command_id
):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    durable = SQLiteHandEventStore(
        tmp_path / f"append-conflict-{preserve_command_id}.sqlite3"
    )
    opened = GameOrchestrator(durable).open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    conflict_store = _ConflictInjectingStore(
        durable, preserve_command_id=preserve_command_id
    )
    command = PlayerActionCommandV1(
        session_id=session.session_id,
        hand_id=hand_id,
        command_id="racing-command",
        expected_sequence=opened.replayed_hand.state.applied_sequence,
        actor_seat=3,
        action="fold",
        amount_semantics="none",
    )

    if preserve_command_id:
        result = GameOrchestrator(conflict_store).execute(session, command)
        assert result.idempotent is True
    else:
        with pytest.raises(GameCommandError) as caught:
            GameOrchestrator(conflict_store).execute(session, command)
        assert caught.value.code == "append_conflict"

    assert conflict_store.append_calls == 1
    assert len(durable.read(hand_id)) == 8
    durable.close()


@pytest.mark.parametrize("preserve_command_id", (True, False))
def test_open_append_conflict_reconciles_only_the_same_durable_command(
    tmp_path, preserve_command_id
):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    durable = SQLiteHandEventStore(
        tmp_path / f"open-append-conflict-{preserve_command_id}.sqlite3"
    )
    conflict_store = _ConflictInjectingStore(
        durable, preserve_command_id=preserve_command_id
    )
    command = OpenHandCommandV1(
        session_id=session.session_id,
        hand_id=hand_id,
        command_id="racing-open-command",
        expected_sequence=0,
        rng_seed=20260812,
    )

    if preserve_command_id:
        result = GameOrchestrator(conflict_store).open_hand(session, command)
        assert result.idempotent is True
    else:
        with pytest.raises(GameCommandError) as caught:
            GameOrchestrator(conflict_store).open_hand(session, command)
        assert caught.value.code == "append_conflict"

    assert conflict_store.append_calls == 1
    assert len(durable.read(hand_id)) == 7
    durable.close()


def test_open_append_conflict_returns_completed_successor_when_winner_finished_hand(
    tmp_path,
):
    winner, _, completed_events = _run_seeded_checkdown(
        tmp_path / "completed-open-winner.sqlite3"
    )
    session = _opened_session()
    assert session.active_hand is not None
    durable = SQLiteHandEventStore(tmp_path / "completed-open-conflict.sqlite3")
    conflict_store = _CompletedOpenConflictStore(durable, completed_events)

    result = GameOrchestrator(conflict_store).open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=session.active_hand.hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )

    assert result.idempotent is True
    assert result.session.active_hand is None
    assert result.session.completed_hand_ids == (session.active_hand.hand_id,)
    assert result.session.topology == winner.session.topology
    assert conflict_store.append_calls == 1
    durable.close()


def test_restart_recovers_only_from_opening_facts_and_durable_events(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    path = tmp_path / "restart.sqlite3"
    first_store = SQLiteHandEventStore(path)
    first = GameOrchestrator(first_store)
    opened = first.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    folded = first.execute(
        session,
        PlayerActionCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="fold-before-restart",
            expected_sequence=opened.replayed_hand.state.applied_sequence,
            actor_seat=3,
            action="fold",
            amount_semantics="none",
        ),
    )
    first_store.close()

    restarted_store = SQLiteHandEventStore(path)
    continued = GameOrchestrator(restarted_store).execute(
        session,
        PlayerActionCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="fold-after-restart",
            expected_sequence=folded.replayed_hand.state.applied_sequence,
            actor_seat=4,
            action="fold",
            amount_semantics="none",
        ),
    )
    assert continued.replayed_hand.state.folded_seats == (3, 4)
    assert len(restarted_store.read(hand_id)) == 9

    mismatched_session = _opened_session_with_stacks(
        (9_999, 10_001, 10_000, 10_000, 10_000, 10_000)
    )
    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(restarted_store).execute(
            mismatched_session,
            PlayerActionCommandV1(
                session_id=mismatched_session.session_id,
                hand_id=hand_id,
                command_id="mismatched-opening",
                expected_sequence=continued.replayed_hand.state.applied_sequence,
                actor_seat=5,
                action="fold",
                amount_semantics="none",
            ),
        )
    assert caught.value.code == "opening_facts_mismatch"
    assert len(restarted_store.read(hand_id)) == 9
    restarted_store.close()


def test_completed_hand_rejects_new_action_and_terminal_retry_cannot_resettle(tmp_path):
    session = _opened_session()
    assert session.active_hand is not None
    hand_id = session.active_hand.hand_id
    store = SQLiteHandEventStore(tmp_path / "completed-hand.sqlite3")
    orchestrator = GameOrchestrator(store)
    result = orchestrator.open_hand(
        session,
        OpenHandCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id="open-command-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    terminal_command = None
    for index, actor in enumerate((3, 4, 5, 0, 1), start=1):
        terminal_command = PlayerActionCommandV1(
            session_id=session.session_id,
            hand_id=hand_id,
            command_id=f"terminal-fold-{index}",
            expected_sequence=result.replayed_hand.state.applied_sequence,
            actor_seat=actor,
            action="fold",
            amount_semantics="none",
        )
        result = orchestrator.execute(session, terminal_command)
    assert terminal_command is not None
    durable_count = len(store.read(hand_id))

    duplicate = GameOrchestrator(store).execute(result.session, terminal_command)
    assert duplicate.idempotent is True
    assert duplicate.session == result.session
    assert len(store.read(hand_id)) == durable_count

    with pytest.raises(GameCommandError) as caught:
        GameOrchestrator(store).execute(
            result.session,
            PlayerActionCommandV1(
                session_id=session.session_id,
                hand_id=hand_id,
                command_id="late-action",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=2,
                action="check",
                amount_semantics="none",
            ),
        )
    assert caught.value.code == "hand_completed"
    assert len(store.read(hand_id)) == durable_count
    assert sum(
        item.event.payload.kind == "hand_completed" for item in store.read(hand_id)
    ) == 1
    store.close()
