"""Public contracts owned by the hand-review subsystem."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StrictInt

from poker_coach.domain.models import DomainModel, SeatNumber, StateSnapshot, Street


class DecisionSnapshot(DomainModel):
    """The PokerKit-verified state immediately before one player decision."""

    action_id: str = Field(min_length=1, max_length=128)
    event_sequence: Annotated[StrictInt, Field(ge=1)]
    decision_sequence: Annotated[StrictInt, Field(ge=0)]
    street: Street
    actor_seat: SeatNumber
    state_before_action: StateSnapshot
