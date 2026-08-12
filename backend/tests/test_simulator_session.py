"""Focused ownership and lifecycle tests for the F1-01 GameSession seam."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from poker_coach.simulator import (
    DEFAULT_BIG_BLIND,
    DEFAULT_SMALL_BLIND,
    DEFAULT_STARTING_STACK,
    FirstProductTableConfigV1,
    GameSession,
    SeatTopologyV1,
    SessionLifecycleError,
    SessionSeatV1,
)


def _seats(count: int = 6, *, sitting_out: tuple[int, ...] = ()) -> tuple[SessionSeatV1, ...]:
    return tuple(
        SessionSeatV1(
            seat_id=seat_id,
            stack=DEFAULT_STARTING_STACK,
            sitting_out=seat_id in sitting_out,
        )
        for seat_id in range(count)
    )


def _session(**updates: object) -> GameSession:
    values: dict[str, object] = {
        "session_id": "session-alpha",
        "seats": _seats(),
        "button_seat": 0,
    }
    values.update(updates)
    return GameSession.create(**values)


def test_session_and_hand_ids_are_stable_and_owned_by_their_session():
    session = _session()
    opened = session.start_next_hand()

    assert opened.session_id == "session-alpha"
    assert opened.active_hand is not None
    assert opened.active_hand.session_id == opened.session_id
    assert opened.active_hand.hand_id == "session-alpha:hand:1"
    assert opened.active_hand.sequence == 1

    with pytest.raises(ValidationError, match="belongs to another session"):
        GameSession.model_validate(
            {
                **opened.model_dump(),
                "active_hand": {
                    **opened.active_hand.model_dump(),
                    "session_id": "another-session",
                },
            }
        )


def test_first_product_defaults_are_frozen_and_reject_non_product_config():
    config = FirstProductTableConfigV1()

    assert config.ruleset == "nlhe"
    assert config.table_size == 6
    assert config.small_blind == DEFAULT_SMALL_BLIND
    assert config.big_blind == DEFAULT_BIG_BLIND
    assert config.starting_stack == DEFAULT_STARTING_STACK
    assert config.ante == 0
    assert config.rake_bps == 0

    for invalid in (
        {"ruleset": "plo"},
        {"tableSize": 5},
        {"smallBlind": 25},
        {"bigBlind": 200},
        {"ante": 1},
        {"rakeBps": 1},
        {"startingStack": 9_900},
    ):
        with pytest.raises(ValidationError):
            FirstProductTableConfigV1.model_validate(invalid)

    with pytest.raises(ValueError, match="100BB starting stacks"):
        _session(seats=(*_seats()[:-1], SessionSeatV1(seat_id=5, stack=9_900)))


@pytest.mark.parametrize("seat_count", (2, 8))
def test_topology_accepts_the_2_to_8_boundary_without_publishing_other_modes(
    seat_count: int,
):
    topology = SeatTopologyV1(seats=_seats(seat_count))

    assert len(topology.seats) == seat_count
    assert tuple(seat.seat_id for seat in topology.participating_seats) == tuple(
        range(seat_count)
    )


@pytest.mark.parametrize("seat_count", (1, 9))
def test_topology_rejects_counts_outside_2_to_8(seat_count: int):
    with pytest.raises(ValidationError):
        SeatTopologyV1(seats=_seats(seat_count))


def test_topology_rejects_gaps_and_too_few_participants():
    with pytest.raises(ValidationError, match="contiguous"):
        SeatTopologyV1(
            seats=(
                SessionSeatV1(seat_id=0, stack=10_000),
                SessionSeatV1(seat_id=2, stack=10_000),
            )
        )
    with pytest.raises(ValidationError, match="at least two"):
        SeatTopologyV1(seats=_seats(2, sitting_out=(1,)))


def test_button_rotates_past_sitting_out_seats_without_changing_their_stack():
    session = _session(seats=_seats(sitting_out=(1, 2)), button_seat=0)
    first = session.start_next_hand()
    assert first.active_hand is not None
    assert tuple(seat.seat_id for seat in first.active_hand.seats) == (0, 3, 4, 5)

    closed = first.complete_active_hand(hand_id=first.active_hand.hand_id)
    assert closed.button_seat == 3
    assert closed.topology.seats[1].stack == DEFAULT_STARTING_STACK
    assert closed.topology.seats[2].stack == DEFAULT_STARTING_STACK


def test_one_hand_must_finish_before_the_next_starts_and_ids_never_repeat():
    session = _session()
    first = session.start_next_hand()
    assert first.active_hand is not None

    with pytest.raises(SessionLifecycleError, match="cannot start") as start_error:
        first.start_next_hand()
    assert start_error.value.code == "hand_in_progress"

    with pytest.raises(SessionLifecycleError, match="not the session") as ownership_error:
        first.complete_active_hand(hand_id="session-alpha:hand:99")
    assert ownership_error.value.code == "hand_ownership_mismatch"

    closed = first.complete_active_hand(hand_id=first.active_hand.hand_id)
    second = closed.start_next_hand()
    assert second.active_hand is not None
    assert closed.button_seat == 1
    assert second.active_hand.sequence == 2
    assert second.active_hand.hand_id == "session-alpha:hand:2"
    assert second.active_hand.hand_id not in closed.completed_hand_ids


def test_session_seam_never_silently_changes_session_or_hand_stack_ownership():
    session = _session()
    original_stacks = tuple(seat.stack for seat in session.topology.seats)
    opened = session.start_next_hand()
    assert opened.active_hand is not None
    snapshot_stacks = tuple(seat.starting_stack for seat in opened.active_hand.seats)

    closed = opened.complete_active_hand(hand_id=opened.active_hand.hand_id)
    assert tuple(seat.stack for seat in session.topology.seats) == original_stacks
    assert tuple(seat.stack for seat in opened.topology.seats) == original_stacks
    assert tuple(seat.stack for seat in closed.topology.seats) == original_stacks
    assert snapshot_stacks == original_stacks


def test_busted_seat_remains_in_session_but_is_excluded_from_the_next_hand():
    opened = _session().start_next_hand()
    assert opened.active_hand is not None

    settled = opened.complete_active_hand(
        hand_id=opened.active_hand.hand_id,
        ending_stacks={0: 0, 1: 20_000, 2: 10_000, 3: 10_000, 4: 10_000, 5: 10_000},
    )
    next_hand = settled.start_next_hand()

    assert settled.topology.seats[0].stack == 0
    assert next_hand.active_hand is not None
    assert tuple(seat.seat_id for seat in next_hand.active_hand.seats) == (1, 2, 3, 4, 5)


def test_button_rotation_skips_a_zero_stack_seat():
    opened = _session().start_next_hand()
    assert opened.active_hand is not None

    settled = opened.complete_active_hand(
        hand_id=opened.active_hand.hand_id,
        ending_stacks={0: 20_000, 1: 0, 2: 10_000, 3: 10_000, 4: 10_000, 5: 10_000},
    )

    assert settled.button_seat == 2


def test_session_with_fewer_than_two_funded_seats_cannot_start_another_hand():
    opened = _session().start_next_hand()
    assert opened.active_hand is not None
    settled = opened.complete_active_hand(
        hand_id=opened.active_hand.hand_id,
        ending_stacks={0: 60_000, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
    )

    with pytest.raises(SessionLifecycleError) as caught:
        settled.start_next_hand()

    assert caught.value.code == "insufficient_funded_seats"
