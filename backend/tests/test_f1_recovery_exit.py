"""F1-07 exit-gate tests over real SQLite files and public simulator seams."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from poker_coach.persistence import (
    SessionRevisionConflict,
    SQLiteGameSessionStore,
    SQLiteHandEventStore,
    SQLiteProjectionStore,
)
from poker_coach.rules import PokerKitAdapter
from poker_coach.simulator import (
    AmountSemanticsV1,
    GameOrchestrator,
    GameSession,
    OpenHandCommandV1,
    OutboxDispatcher,
    OutboxIntentV1,
    PlayerActionCommandV1,
    ProjectionIdentityV1,
    ProjectionRunner,
    SessionSeatV1,
    SimulatorActionV1,
    build_observation,
    replay_hand,
    scenario_from_events,
)


def _new_session(session_id: str) -> GameSession:
    return GameSession.create(
        session_id=session_id,
        seats=tuple(
            SessionSeatV1(seat_id=seat_id, stack=10_000)
            for seat_id in range(6)
        ),
    )


class _ProjectionOutboxEventStore:
    """Test adapter that binds one projection intent to every appended fact."""

    def __init__(self, store: SQLiteHandEventStore):
        self.store = store

    def append(self, *, hand_id, expected_sequence, events, outbox_intents=()):
        bound = tuple(
            OutboxIntentV1.for_event(
                event_id=item.event.event_id,
                purpose="projection_refresh",
                topic="hand.projection.refresh",
                payload={"handId": hand_id, "sequence": item.event.sequence},
            )
            for item in events
        )
        return self.store.append(
            hand_id=hand_id,
            expected_sequence=expected_sequence,
            events=events,
            outbox_intents=(*outbox_intents, *bound),
        )

    def read(self, hand_id):
        return self.store.read(hand_id)


def _play_policy_hand(
    store: SQLiteHandEventStore,
    session: GameSession,
    *,
    rng_seed: int,
    policy: str,
):
    opened = session.start_next_hand()
    assert opened.active_hand is not None
    hand_id = opened.active_hand.hand_id
    orchestrator = GameOrchestrator(store)
    result = orchestrator.open_hand(
        opened,
        OpenHandCommandV1(
            session_id=opened.session_id,
            hand_id=hand_id,
            command_id=f"{hand_id}:open",
            expected_sequence=0,
            rng_seed=rng_seed,
        ),
    )
    adapter = PokerKitAdapter()
    action_count = 0
    while result.replayed_hand.state.hand_in_progress:
        durable = tuple(item.event for item in store.read(hand_id))
        state = adapter.replay(scenario_from_events(durable)).final_state
        assert state.actor_seat is not None
        observation = build_observation(
            durable,
            observer_seat=state.actor_seat,
            after_sequence=durable[-1].sequence,
            adapter=adapter,
        )
        priority = (
            (SimulatorActionV1.FOLD,)
            if policy == "fold"
            else (
                SimulatorActionV1.CHECK,
                SimulatorActionV1.CALL,
                SimulatorActionV1.FOLD,
            )
        )
        legal = next(
            candidate
            for action in priority
            for candidate in observation.legal_actions
            if candidate.action is action
        )
        amount = (
            None
            if legal.amount_semantics is AmountSemanticsV1.NONE
            else legal.max_amount
        )
        assert legal.accepts(action=legal.action, amount=amount)
        action_count += 1
        result = orchestrator.execute(
            opened,
            PlayerActionCommandV1(
                session_id=opened.session_id,
                hand_id=hand_id,
                command_id=f"{hand_id}:action:{action_count}",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=observation.observer_seat,
                action=legal.action,
                amount=amount,
                amount_semantics=legal.amount_semantics,
            ),
        )
    durable = tuple(item.event for item in store.read(hand_id))
    return opened, result, durable, action_count


def _assert_completed_hand_invariants(opened, result, durable):
    assert opened.active_hand is not None
    assert result.session.active_hand is None
    assert [event.sequence for event in durable] == list(range(1, len(durable) + 1))
    assert durable[-1].payload.kind == "hand_completed"
    replayed = replay_hand(durable)
    assert replayed.state.fingerprint == result.replayed_hand.state.fingerprint
    assert replayed.state.winner_seats == durable[-1].payload.winner_seats
    assert replayed.state.payouts == durable[-1].payload.payouts
    opening_total = sum(seat.starting_stack for seat in opened.active_hand.seats)
    assert sum(replayed.state.stacks.values()) == opening_total
    assert sum(seat.stack for seat in result.session.topology.seats) == sum(
        seat.stack for seat in opened.topology.seats
    )


def test_real_sqlite_restart_recovers_mid_hand_and_cross_hand_session_progression(
    tmp_path,
):
    path = tmp_path / "authoritative-session.sqlite3"
    session_store = SQLiteGameSessionStore(path)
    event_store = SQLiteHandEventStore(path)
    initial = session_store.save(_new_session("session-restart"), expected_revision=0)
    opened_session = initial.session.start_next_hand()
    opened = session_store.save(opened_session, expected_revision=initial.revision)
    assert opened.session.active_hand is not None
    hand_id = opened.session.active_hand.hand_id

    orchestrator = GameOrchestrator(event_store)
    result = orchestrator.open_hand(
        opened.session,
        OpenHandCommandV1(
            session_id=opened.session.session_id,
            hand_id=hand_id,
            command_id="open-hand-1",
            expected_sequence=0,
            rng_seed=20260812,
        ),
    )
    before_restart = PlayerActionCommandV1(
        session_id=opened.session.session_id,
        hand_id=hand_id,
        command_id="fold-1",
        expected_sequence=result.replayed_hand.state.applied_sequence,
        actor_seat=3,
        action="fold",
        amount_semantics="none",
    )
    result = orchestrator.execute(opened.session, before_restart)
    fingerprint_before_restart = result.replayed_hand.state.fingerprint
    sequence_before_restart = result.replayed_hand.state.applied_sequence
    session_store.close()
    event_store.close()

    restarted_sessions = SQLiteGameSessionStore(path)
    restarted_events = SQLiteHandEventStore(path)
    recovered_mid_hand = restarted_sessions.recover(
        "session-restart", event_store=restarted_events
    )
    assert recovered_mid_hand == opened
    durable_mid_hand = tuple(item.event for item in restarted_events.read(hand_id))
    assert replay_hand(durable_mid_hand).state.fingerprint == fingerprint_before_restart

    restarted_orchestrator = GameOrchestrator(restarted_events)
    after_restart = PlayerActionCommandV1(
        session_id=opened.session.session_id,
        hand_id=hand_id,
        command_id="fold-2",
        expected_sequence=sequence_before_restart,
        actor_seat=4,
        action="fold",
        amount_semantics="none",
    )
    result = restarted_orchestrator.execute(recovered_mid_hand.session, after_restart)
    duplicate = restarted_orchestrator.execute(recovered_mid_hand.session, after_restart)
    assert duplicate.idempotent is True
    assert duplicate.replayed_hand.state.fingerprint == result.replayed_hand.state.fingerprint

    for index, actor in enumerate((5, 0, 1), start=3):
        result = restarted_orchestrator.execute(
            recovered_mid_hand.session,
            PlayerActionCommandV1(
                session_id=opened.session.session_id,
                hand_id=hand_id,
                command_id=f"fold-{index}",
                expected_sequence=result.replayed_hand.state.applied_sequence,
                actor_seat=actor,
                action="fold",
                amount_semantics="none",
            ),
        )
    assert result.session.active_hand is None
    terminal_fingerprint = result.replayed_hand.state.fingerprint
    terminal_stacks = tuple(seat.stack for seat in result.session.topology.seats)

    # Simulate a crash after the terminal event append but before saving the successor.
    restarted_sessions.close()
    restarted_events.close()
    final_sessions = SQLiteGameSessionStore(path)
    final_events = SQLiteHandEventStore(path)
    recovered_terminal = final_sessions.recover(
        "session-restart", event_store=final_events
    )
    assert recovered_terminal.session == result.session
    assert tuple(seat.stack for seat in recovered_terminal.session.topology.seats) == terminal_stacks
    assert recovered_terminal.session.button_seat == 1

    # Retrying the lost session write is idempotent even with the prior revision.
    assert final_sessions.save(
        result.session, expected_revision=opened.revision
    ) == recovered_terminal
    next_hand = recovered_terminal.session.start_next_hand()
    persisted_next = final_sessions.save(
        next_hand, expected_revision=recovered_terminal.revision
    )
    assert persisted_next.session.active_hand is not None
    assert persisted_next.session.active_hand.hand_id == "session-restart:hand:2"
    assert persisted_next.session.active_hand.button_seat == 1
    assert tuple(
        seat.starting_stack for seat in persisted_next.session.active_hand.seats
    ) == terminal_stacks
    with pytest.raises(SessionRevisionConflict) as stale:
        final_sessions.save(opened.session, expected_revision=opened.revision)
    assert stale.value.code == "session_revision_conflict"

    durable = tuple(item.event for item in final_events.read(hand_id))
    assert [event.sequence for event in durable] == list(range(1, len(durable) + 1))
    assert replay_hand(durable).state.fingerprint == terminal_fingerprint
    final_sessions.close()
    final_events.close()


def test_projection_outbox_and_backup_restore_keep_authoritative_fingerprint(tmp_path):
    source_path = tmp_path / "rebuild-source.sqlite3"
    backup_path = tmp_path / "rebuild-backup.sqlite3"
    current_time = [datetime(2026, 8, 12, tzinfo=timezone.utc)]
    sessions = SQLiteGameSessionStore(source_path)
    raw_events = SQLiteHandEventStore(source_path, clock=lambda: current_time[0])
    projections = SQLiteProjectionStore(source_path)
    stored = sessions.save(_new_session("session-rebuild"), expected_revision=0)
    stored = sessions.save(
        stored.session.start_next_hand(), expected_revision=stored.revision
    )
    assert stored.session.active_hand is not None
    hand_id = stored.session.active_hand.hand_id
    orchestrator = GameOrchestrator(_ProjectionOutboxEventStore(raw_events))
    result = orchestrator.open_hand(
        stored.session,
        OpenHandCommandV1(
            session_id=stored.session.session_id,
            hand_id=hand_id,
            command_id="open-rebuild",
            expected_sequence=0,
            rng_seed=20260813,
        ),
    )
    terminal_command = None
    for index, actor in enumerate((3, 4, 5, 0, 1), start=1):
        terminal_command = PlayerActionCommandV1(
            session_id=stored.session.session_id,
            hand_id=hand_id,
            command_id=f"rebuild-fold-{index}",
            expected_sequence=result.replayed_hand.state.applied_sequence,
            actor_seat=actor,
            action="fold",
            amount_semantics="none",
        )
        result = orchestrator.execute(stored.session, terminal_command)
    assert terminal_command is not None
    terminal_retry = orchestrator.execute(result.session, terminal_command)
    assert terminal_retry.idempotent is True
    durable = tuple(item.event for item in raw_events.read(hand_id))
    authoritative_fingerprint = replay_hand(durable).state.fingerprint
    stored = sessions.save(result.session, expected_revision=stored.revision)

    identity = ProjectionIdentityV1(
        projection_name="f1_exit_event_log",
        projection_version=1,
    )

    def projector(snapshot, event):
        return {
            "eventIds": [*(snapshot or {}).get("eventIds", []), event.event_id],
            "lastSequence": event.sequence,
        }

    runner = ProjectionRunner(raw_events, projections, identity, projector)
    incremental = runner.run(hand_id)
    rebuilt = runner.rebuild(hand_id)
    assert rebuilt.payload == incremental.payload
    assert rebuilt.fingerprint == incremental.fingerprint
    assert rebuilt.sequence == len(durable)

    delivered: set[str] = set()
    dispatch_result = OutboxDispatcher(raw_events).dispatch_once(
        worker_id="f1-exit",
        dispatch=lambda message: delivered.add(message.idempotency_key),
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert dispatch_result.claimed_count == len(durable)
    assert dispatch_result.dispatched_count == len(durable)
    assert dispatch_result.failed_count == 0
    assert len(delivered) == len(durable)

    projections.close()
    sessions.close()
    raw_events.close()
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)

    restored_sessions = SQLiteGameSessionStore(backup_path)
    restored_events = SQLiteHandEventStore(backup_path)
    restored_projections = SQLiteProjectionStore(backup_path)
    assert restored_sessions.load("session-rebuild") == stored
    restored_durable = tuple(item.event for item in restored_events.read(hand_id))
    assert replay_hand(restored_durable).state.fingerprint == authoritative_fingerprint
    assert [event.to_json() for event in restored_durable] == [
        event.to_json() for event in durable
    ]
    restored_runner = ProjectionRunner(
        restored_events, restored_projections, identity, projector
    )
    restored_rebuild = restored_runner.rebuild(hand_id)
    assert restored_rebuild.payload == rebuilt.payload
    assert restored_rebuild.fingerprint == rebuilt.fingerprint
    empty_dispatch = OutboxDispatcher(restored_events).dispatch_once(
        worker_id="f1-exit-restored",
        dispatch=lambda message: delivered.add(message.idempotency_key),
        now=datetime(2026, 8, 12, 0, 1, tzinfo=timezone.utc),
    )
    assert empty_dispatch.claimed_count == 0
    assert len(delivered) == len(durable)
    restored_projections.close()
    restored_sessions.close()
    restored_events.close()


def test_fixed_seed_six_max_one_thousand_hand_soak_covers_f1_exit_invariants():
    store = SQLiteHandEventStore(":memory:")
    hand_count = 0
    legal_action_count = 0
    fold_completions = 0
    normal_completions = 0

    continuous = _new_session("soak-continuous")
    for hand_number in range(1, 998):
        opened, result, durable, actions = _play_policy_hand(
            store,
            continuous,
            rng_seed=202608120000 + hand_number,
            policy="fold",
        )
        _assert_completed_hand_invariants(opened, result, durable)
        continuous = result.session
        hand_count += 1
        legal_action_count += actions
        fold_completions += 1
    assert continuous.hand_sequence == 997
    assert len(continuous.completed_hand_ids) == 997
    assert sum(seat.stack for seat in continuous.topology.seats) == 60_000

    opened, result, durable, actions = _play_policy_hand(
        store,
        _new_session("soak-checkdown"),
        rng_seed=202608129998,
        policy="checkdown",
    )
    _assert_completed_hand_invariants(opened, result, durable)
    assert len(result.replayed_hand.state.board) == 5
    hand_count += 1
    legal_action_count += actions
    normal_completions += 1

    side_pot_session = GameSession.model_validate(
        {
            "sessionId": "soak-side-pot",
            "topology": {
                "seats": [
                    {"seatId": seat_id, "stack": stack}
                    for seat_id, stack in enumerate(
                        (3_000, 2_000, 5_000, 10_000, 10_000, 30_000)
                    )
                ]
            },
            "buttonSeat": 0,
        }
    )
    side_pot_opened = side_pot_session.start_next_hand()
    assert side_pot_opened.active_hand is not None
    side_pot_hand_id = side_pot_opened.active_hand.hand_id
    orchestrator = GameOrchestrator(store)
    side_pot_result = orchestrator.open_hand(
        side_pot_opened,
        OpenHandCommandV1(
            session_id=side_pot_opened.session_id,
            hand_id=side_pot_hand_id,
            command_id="soak-side-pot:open",
            expected_sequence=0,
            rng_seed=20260813,
        ),
    )
    side_pot_actions = (
        (3, "fold", None, "none"),
        (4, "fold", None, "none"),
        (5, "fold", None, "none"),
        (0, "raise", 3_000, "to"),
        (1, "call", 1_950, "cost"),
        (2, "call", 2_900, "cost"),
    )
    for index, (actor, action, amount, semantics) in enumerate(
        side_pot_actions, start=1
    ):
        side_pot_result = orchestrator.execute(
            side_pot_opened,
            PlayerActionCommandV1(
                session_id=side_pot_opened.session_id,
                hand_id=side_pot_hand_id,
                command_id=f"soak-side-pot:action:{index}",
                expected_sequence=side_pot_result.replayed_hand.state.applied_sequence,
                actor_seat=actor,
                action=action,
                amount=amount,
                amount_semantics=semantics,
            ),
        )
    side_pot_durable = tuple(item.event for item in store.read(side_pot_hand_id))
    _assert_completed_hand_invariants(
        side_pot_opened, side_pot_result, side_pot_durable
    )
    assert len(side_pot_result.replayed_hand.state.board) == 5
    assert side_pot_result.replayed_hand.state.payouts
    assert sum(side_pot_result.replayed_hand.state.payouts.values()) == 8_000
    assert any(seat.stack == 0 for seat in side_pot_result.session.topology.seats)
    hand_count += 1
    legal_action_count += len(side_pot_actions)

    sparse_opened, sparse_result, sparse_durable, actions = _play_policy_hand(
        store,
        side_pot_result.session,
        rng_seed=202608121000,
        policy="fold",
    )
    assert sparse_opened.active_hand is not None
    assert 2 <= len(sparse_opened.active_hand.seats) < 6
    assert tuple(seat.seat_id for seat in sparse_opened.active_hand.seats) != tuple(
        range(len(sparse_opened.active_hand.seats))
    )
    _assert_completed_hand_invariants(sparse_opened, sparse_result, sparse_durable)
    hand_count += 1
    legal_action_count += actions
    fold_completions += 1

    assert hand_count == 1_000
    assert legal_action_count > 4_000
    assert fold_completions == 998
    assert normal_completions == 1
    store.close()
