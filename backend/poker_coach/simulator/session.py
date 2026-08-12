"""Authoritative ownership seam for a continuous cash-game session.

This module owns only session identity, table membership, button progression,
and the immutable stack snapshot with which each hand starts.  It deliberately
does not deal cards, post blinds, validate actions, calculate payouts, or
change stacks: those are PokerKit-orchestrator responsibilities in F1-03.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, StrictStr, model_validator

from poker_coach.domain.models import ChipAmount, DomainModel, PositiveChipAmount, SeatNumber


SessionId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
HandId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
HandSequence = Annotated[StrictInt, Field(ge=0)]

DEFAULT_SMALL_BLIND = 50
DEFAULT_BIG_BLIND = 100
DEFAULT_STARTING_STACK = 10_000


class SessionLifecycleError(ValueError):
    """A rejected GameSession lifecycle transition with a stable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SessionSeatV1(DomainModel):
    """A persistent seat owned by the session, not by an individual hand."""

    model_config = ConfigDict(frozen=True)

    seat_id: SeatNumber
    stack: ChipAmount
    sitting_out: bool = False


class SeatTopologyV1(DomainModel):
    """Validate the 2--8-seat domain topology without publishing table modes."""

    model_config = ConfigDict(frozen=True)

    seats: tuple[SessionSeatV1, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_topology(self) -> SeatTopologyV1:
        seat_ids = tuple(seat.seat_id for seat in self.seats)
        if seat_ids != tuple(range(len(self.seats))):
            raise ValueError("seats must use contiguous IDs 0..table_size-1")
        if sum(not seat.sitting_out for seat in self.seats) < 2:
            raise ValueError("at least two seats must be participating")
        return self

    @property
    def participating_seats(self) -> tuple[SessionSeatV1, ...]:
        """Seats eligible for the next hand; sitting-out seats retain their stack."""

        return tuple(seat for seat in self.seats if not seat.sitting_out)


class FirstProductTableConfigV1(DomainModel):
    """The only released configuration: 6-max NLHE, 100BB, no ante or rake."""

    model_config = ConfigDict(frozen=True)

    ruleset: Literal["nlhe"] = "nlhe"
    table_size: Literal[6] = 6
    small_blind: Literal[DEFAULT_SMALL_BLIND] = DEFAULT_SMALL_BLIND
    big_blind: Literal[DEFAULT_BIG_BLIND] = DEFAULT_BIG_BLIND
    ante: Literal[0] = 0
    rake_bps: Literal[0] = 0
    starting_stack: Literal[DEFAULT_STARTING_STACK] = DEFAULT_STARTING_STACK


class HandSeatSnapshotV1(DomainModel):
    """A hand-owned copy of a participating seat's session-owned stack."""

    model_config = ConfigDict(frozen=True)

    seat_id: SeatNumber
    starting_stack: PositiveChipAmount


class ActiveHandV1(DomainModel):
    """One open hand and its immutable session-owned opening facts."""

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    hand_id: HandId
    sequence: Annotated[StrictInt, Field(ge=1)]
    button_seat: SeatNumber
    seats: tuple[HandSeatSnapshotV1, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_hand_snapshot(self) -> ActiveHandV1:
        seat_ids = tuple(seat.seat_id for seat in self.seats)
        if len(seat_ids) != len(set(seat_ids)):
            raise ValueError("a hand snapshot cannot repeat a seat")
        if self.button_seat not in seat_ids:
            raise ValueError("button_seat must participate in the active hand")
        return self


class GameSession(DomainModel):
    """Immutable aggregate that owns hands, seats, button, config, and stacks.

    Calling a transition returns a replacement aggregate.  The caller must keep
    that returned instance as the authoritative session state; prior instances
    remain usable audit values and cannot be changed through this seam.
    """

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    configuration: FirstProductTableConfigV1 = Field(
        default_factory=FirstProductTableConfigV1
    )
    topology: SeatTopologyV1
    button_seat: SeatNumber
    hand_sequence: HandSequence = 0
    completed_hand_ids: tuple[HandId, ...] = ()
    active_hand: ActiveHandV1 | None = None

    @model_validator(mode="after")
    def validate_session_ownership(self) -> GameSession:
        if len(self.topology.seats) != self.configuration.table_size:
            raise ValueError("first-product sessions require exactly six table seats")
        if self.button_seat >= len(self.topology.seats):
            raise ValueError("button_seat must reference a table seat")
        if self.button_seat not in {
            seat.seat_id for seat in self.topology.participating_seats
        }:
            raise ValueError("button_seat must reference a participating seat")
        if len(self.completed_hand_ids) != len(set(self.completed_hand_ids)):
            raise ValueError("completed_hand_ids must be unique")
        expected_started = len(self.completed_hand_ids) + int(self.active_hand is not None)
        if self.hand_sequence != expected_started:
            raise ValueError("hand_sequence must equal the number of started hands")
        for sequence, hand_id in enumerate(self.completed_hand_ids, start=1):
            if hand_id != self._hand_id_for(sequence):
                raise ValueError("completed hand ID does not belong to this session")
        if self.active_hand is not None:
            if self.active_hand.session_id != self.session_id:
                raise ValueError("active hand belongs to another session")
            if self.active_hand.sequence != self.hand_sequence:
                raise ValueError("active hand sequence must be current")
            if self.active_hand.hand_id != self._hand_id_for(self.hand_sequence):
                raise ValueError("active hand ID does not belong to this session")
            if self.active_hand.button_seat != self.button_seat:
                raise ValueError("active hand button must match the session button")
        return self

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        seats: tuple[SessionSeatV1, ...],
        button_seat: int = 0,
        configuration: FirstProductTableConfigV1 | None = None,
    ) -> GameSession:
        """Create a new first-product session with no active hand."""

        config = configuration or FirstProductTableConfigV1()
        if any(seat.stack != config.starting_stack for seat in seats):
            raise ValueError("first-product sessions require 100BB starting stacks")
        return cls(
            session_id=session_id,
            configuration=config,
            topology=SeatTopologyV1(seats=seats),
            button_seat=button_seat,
        )

    def start_next_hand(self) -> GameSession:
        """Open exactly one new hand from current stacks without changing them."""

        if self.active_hand is not None:
            raise SessionLifecycleError(
                "hand_in_progress", "cannot start a hand while another hand is active"
            )
        sequence = self.hand_sequence + 1
        active_hand = ActiveHandV1(
            session_id=self.session_id,
            hand_id=self._hand_id_for(sequence),
            sequence=sequence,
            button_seat=self.button_seat,
            seats=tuple(
                HandSeatSnapshotV1(seat_id=seat.seat_id, starting_stack=seat.stack)
                for seat in self.topology.participating_seats
            ),
        )
        return self._replace(hand_sequence=sequence, active_hand=active_hand)

    def complete_active_hand(
        self,
        *,
        hand_id: str,
        ending_stacks: dict[int, int] | None = None,
    ) -> GameSession:
        """Close the active hand and rotate the button for the following hand.

        This is an ownership transition only.  F1-03 must invoke it only after
        PokerKit has accepted a completed hand and has supplied any stack updates.
        """

        if self.active_hand is None:
            raise SessionLifecycleError("no_active_hand", "no active hand can be completed")
        if hand_id != self.active_hand.hand_id:
            raise SessionLifecycleError(
                "hand_ownership_mismatch", "hand ID is not the session's active hand"
            )
        topology = self.topology
        if ending_stacks is not None:
            active_seats = {seat.seat_id for seat in self.active_hand.seats}
            if set(ending_stacks) != active_seats:
                raise SessionLifecycleError(
                    "settlement_seat_mismatch",
                    "ending stacks must contain exactly the active hand seats",
                )
            if any(amount < 0 for amount in ending_stacks.values()):
                raise SessionLifecycleError(
                    "invalid_ending_stack", "ending stacks must be non-negative"
                )
            opening_total = sum(
                seat.starting_stack for seat in self.active_hand.seats
            )
            if sum(ending_stacks.values()) != opening_total:
                raise SessionLifecycleError(
                    "chip_conservation",
                    "ending stacks must conserve the active hand's opening chips",
                )
            topology = SeatTopologyV1(
                seats=tuple(
                    SessionSeatV1(
                        seat_id=seat.seat_id,
                        stack=ending_stacks.get(seat.seat_id, seat.stack),
                        sitting_out=seat.sitting_out,
                    )
                    for seat in self.topology.seats
                )
            )
        return self._replace(
            button_seat=self._next_participating_button(),
            completed_hand_ids=(*self.completed_hand_ids, self.active_hand.hand_id),
            active_hand=None,
            topology=topology,
        )

    def _hand_id_for(self, sequence: int) -> str:
        return f"{self.session_id}:hand:{sequence}"

    def _next_participating_button(self) -> int:
        seats = self.topology.seats
        for offset in range(1, len(seats) + 1):
            candidate = (self.button_seat + offset) % len(seats)
            if not seats[candidate].sitting_out:
                return candidate
        raise AssertionError("validated topology always has participating seats")

    def _replace(self, **updates: object) -> GameSession:
        """Re-validate every transition instead of trusting model_copy updates."""

        return type(self).model_validate({**self.model_dump(), **updates})
